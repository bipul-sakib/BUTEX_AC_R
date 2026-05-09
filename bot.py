import os
import requests
from bs4 import BeautifulSoup
import json
import easyocr
import numpy as np
import re
from PIL import Image, ImageEnhance, ImageOps
from pdf2image import convert_from_path

# --- পরিবেশ সেটআপ ---
if os.environ.get('GITHUB_ACTIONS'):
    POPPLER_PATH = None
else:
    # আপনার পিসির জন্য পাথ (প্রয়োজন হলে পরিবর্তন করুন)
    POPPLER_PATH = r'D:\Projects\Release-24.02.0-0\poppler-24.02.0\Library\bin'

BASE_URL = "https://www.butex.edu.bd/affiliated-colleges/"
MAX_PAGES = 30 

# EasyOCR রিডার লোড করা (শুধুমাত্র ইংরেজি)
reader = easyocr.Reader(['en'], gpu=False)

def decode_roll(roll):
    """রোল থেকে কলেজ এবং ডিপার্টমেন্ট বের করা"""
    roll = str(roll).strip().upper()
    batch, college, dept = "Unknown", "Unknown", "Unknown"
    
    if len(roll) == 11 and roll.isdigit():
        batch = roll[0:2]
        col_code = roll[2:4]
        dept_code = roll[4:6]
        
        colleges = {"02":"Pabna","03":"Chattogram","04":"Barishal","05":"Noakhali","06":"Jhenaidah","07":"TTEC/BTEC","08":"NTEC/BHETI","09":"Rangpur","10":"Gopalganj","11":"Jamalpur","12":"Madaripur","13":"Sylhet"}
        college = colleges.get(col_code, "Unknown")
        
        depts = {"01":"Yarn", "02":"Fabric", "03":"Wet Process", "04":"Apparel"}
        dept = depts.get(dept_code, "Unknown")
        
    return batch, college, dept

def enhance_image(pil_img):
    """ইমেজের মান উন্নত করা যাতে OCR ভালো কাজ করে"""
    gray = ImageOps.grayscale(pil_img)
    # কন্ট্রাস্ট ৩ গুণ বাড়ানো হচ্ছে
    enhanced = ImageEnhance.Contrast(gray).enhance(3.0)
    return np.array(enhanced)

def get_data_ai(pdf_path):
    """AI OCR ব্যবহার করে ডাটা সংগ্রহ"""
    extracted_data = []
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=POPPLER_PATH)
        for page in pages:
            img = enhance_image(page)
            # EasyOCR দিয়ে টেক্সট পড়া
            ocr_results = reader.readtext(img, detail=0)
            text_blob = " ".join(ocr_results)
            
            # রোল (১০-১১ ডিজিট) এবং তার পাশের জিপিএ (X.XX) খোঁজা
            patterns = re.findall(r'(\d{10,11}).*?(\d\.\d{2})', text_blob)
            for roll, gpa in patterns:
                extracted_data.append({"roll": roll, "gpa": float(gpa)})
    except Exception as e:
        print(f"  AI OCR Error: {e}")
    return extracted_data

def calculate_rankings(master_data):
    """কলেজ এবং ডিপার্টমেন্ট ভিত্তিক র‍্যাঙ্কিং"""
    if not master_data: return master_data
    
    student_list = []
    for roll, info in master_data.items():
        if info.get("results"):
            latest_term = sorted(info["results"].keys())[-1]
            student_list.append({
                "roll": roll, 
                "gpa": info["results"][latest_term], 
                "dept": info["dept"], 
                "college": info["college"]
            })
    
    # জিপিএ অনুযায়ী সাজানো
    student_list.sort(key=lambda x: x["gpa"], reverse=True)
    
    college_map = {}
    dept_map = {}

    for s in student_list:
        r, c, d = s["roll"], s["college"], s["dept"]
        
        # কলেজ র‍্যাঙ্ক
        college_map[c] = college_map.get(c, 0) + 1
        master_data[r]["college_rank"] = college_map[c]
        
        # ডিপার্টমেন্ট র‍্যাঙ্ক
        d_key = f"{c}_{d}"
        dept_map[d_key] = dept_map.get(d_key, 0) + 1
        master_data[r]["dept_rank"] = dept_map[d_key]
        
    return master_data

def main():
    print("🤖 AI Based Scraper Starting...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    master_data = {}

    if os.path.exists("data.json"):
        with open("data.json", "r", encoding='utf-8') as f:
            master_data = json.load(f)

    # শুধুমাত্র প্রথম পেজ চেক করা (যদি ডাটা থাকে), না থাকলে সব
    pages = [1] if master_data else range(1, MAX_PAGES + 1)

    for p in pages:
        url = BASE_URL if p == 1 else f"{BASE_URL}page/{p}/"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                title = link.get_text().strip().upper()
                
                if "RESULT" in title and href.startswith("http"):
                    # টার্ম নির্ধারণ (যেমন: L2T1)
                    t_match = re.search(r'LEVEL[- ]?(\d).*?TERM[- ]?(\d|I+)', title)
                    term = f"L{t_match.group(1)}T{1 if t_match.group(2)=='I' else (2 if t_match.group(2)=='II' else t_match.group(2))}" if t_match else "LXTX"
                    
                    print(f"🔍 Scanning: {title[:30]}...")
                    
                    try:
                        post_res = requests.get(href, headers=headers, timeout=15)
                        pdf_soup = BeautifulSoup(post_res.text, 'html.parser')
                        for pdf_link in pdf_soup.find_all('a', href=True):
                            if ".pdf" in pdf_link['href'].lower():
                                pdf_url = pdf_link['href']
                                with open("temp.pdf", "wb") as f:
                                    f.write(requests.get(pdf_url).content)
                                
                                # AI OCR কল করা
                                results = get_data_ai("temp.pdf")
                                for item in results:
                                    roll = item['roll']
                                    if roll not in master_data:
                                        b, col, d = decode_roll(roll)
                                        master_data[roll] = {"name": "Unknown", "batch": b, "college": col, "dept": d, "results": {}}
                                    master_data[roll]["results"][term] = item['gpa']
                                
                                print(f"  ✅ Extracted {len(results)} students.")
                    except Exception as e:
                        print(f"  Error processing post: {e}")

            # প্রতি পেজ শেষে র‍্যাঙ্ক আপডেট এবং সেভ
            master_data = calculate_rankings(master_data)
            with open("data.json", "w", encoding='utf-8') as f:
                json.dump(master_data, f, indent=4)

        except Exception as e:
            print(f"Page Error: {e}")

    if os.path.exists("temp.pdf"): os.remove("temp.pdf")
    print("🏁 Mission Accomplished!")

if __name__ == "__main__":
    main()
