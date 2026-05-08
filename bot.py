import os
import requests
from bs4 import BeautifulSoup
import json
import easyocr
import numpy as np
import re
from PIL import Image, ImageEnhance, ImageOps
from pdf2image import convert_from_path

# --- Paths ---
if os.environ.get('GITHUB_ACTIONS'):
    POPPLER_PATH = None
else:
    POPPLER_PATH = r'D:\Projects\Release-24.02.0-0\poppler-24.02.0\Library\bin'

BASE_URL = "https://www.butex.edu.bd/affiliated-colleges/"
MAX_PAGES = 30 

# Initialize EasyOCR
reader = easyocr.Reader(['en'], gpu=False)

def decode_roll(roll):
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

def enhance_for_ocr(pil_img):
    gray = ImageOps.grayscale(pil_img)
    return np.array(ImageEnhance.Contrast(gray).enhance(3.5))

def get_data_easyocr(pdf_path):
    results = []
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=POPPLER_PATH)
        for page in pages:
            processed_img = enhance_for_ocr(page)
            ocr_results = reader.readtext(processed_img, detail=0)
            full_text = " ".join(ocr_results)
            matches = re.findall(r'([A-Z]?\d{9,11}).*?(\d\.\d{2})', full_text)
            for roll, gpa in matches:
                results.append({"roll": roll.upper(), "gpa": float(gpa)})
    except Exception as e:
        print(f"  OCR Error: {e}")
    return results

def calculate_rankings(master_data):
    if not master_data: return master_data
    student_list = []
    for roll, info in master_data.items():
        if info.get("results"):
            latest_term = sorted(info["results"].keys())[-1]
            student_list.append({"roll": roll, "gpa": info["results"][latest_term], "dept": info["dept"], "college": info["college"]})
    
    student_list.sort(key=lambda x: x["gpa"], reverse=True)
    college_counts, dept_counts = {}, {}
    for s in student_list:
        r, c, d = s["roll"], s["college"], s["dept"]
        college_counts[c] = college_counts.get(c, 0) + 1
        master_data[r]["college_rank"] = college_counts[c]
        d_key = f"{c}_{d}"
        dept_counts[d_key] = dept_counts.get(d_key, 0) + 1
        master_data[r]["dept_rank"] = dept_counts[d_key]
    return master_data

def main():
    print("🚀 AI Scraper started...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    master_data = {}

    if os.path.exists("data.json"):
        with open("data.json", "r", encoding='utf-8') as f:
            master_data = json.load(f)

    # Scrape settings
    pages_to_scrape = [1] if os.environ.get('GITHUB_ACTIONS') and master_data else range(1, MAX_PAGES + 1)

    for page_num in pages_to_scrape:
        print(f"--- Checking Page {page_num} ---")
        url = BASE_URL if page_num == 1 else f"{BASE_URL}page/{page_num}/"
        try:
            res = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                post_url = link['href']
                
                # ফিক্স: ভুল লিঙ্ক বা শুধু '#' বাদ দেওয়া
                if not post_url or post_url == '#' or not post_url.startswith('http'):
                    continue
                
                title = link.get_text().strip()
                if "RESULT" in title.upper() or "ফলাফল" in title.upper():
                    # টার্ম বের করা
                    t_match = re.search(r'LEVEL[- ]?(\d).*?TERM[- ]?(\d|I+)', title.upper())
                    term_key = f"L{t_match.group(1)}T{1 if t_match.group(2)=='I' else (2 if t_match.group(2)=='II' else t_match.group(2))}" if t_match else "LXTX"

                    try:
                        post_res = requests.get(post_url, headers=headers, timeout=15)
                        pdf_soup = BeautifulSoup(post_res.text, 'html.parser')
                        for pdf_link in pdf_soup.find_all('a', href=True):
                            if '.pdf' in pdf_link['href'].lower():
                                print(f"  AI Scanning: {title[:30]}...")
                                pdf_data = requests.get(pdf_link['href']).content
                                with open("temp.pdf", "wb") as f: f.write(pdf_data)
                                
                                extracted = get_data_easyocr("temp.pdf")
                                for item in extracted:
                                    roll = item['roll']
                                    if roll not in master_data:
                                        b, c, d = decode_roll(roll)
                                        master_data[roll] = {"name": "Unknown", "batch": b, "college": c, "dept": d, "results": {}}
                                    master_data[roll]["results"][term_key] = item['gpa']
                    except Exception as e:
                        print(f"  Error on link: {e}")

            # প্রতি পেজ শেষে র‍্যাঙ্কিং আপডেট ও সেভ
            master_data = calculate_rankings(master_data)
            with open("data.json", "w", encoding='utf-8') as f:
                json.dump(master_data, f, indent=4)
                
        except Exception as e:
            print(f"Page error: {e}")

    # কাজ শেষ হোক বা না হোক, অন্তত একটি ফাইল সেভ করবেই
    if not os.path.exists("data.json") or not master_data:
        with open("data.json", "w", encoding='utf-8') as f:
            json.dump({}, f)

    if os.path.exists("temp.pdf"): os.remove("temp.pdf")
    print(f"✅ Scraping Complete. Found {len(master_data)} students.")

if __name__ == "__main__":
    main()
