import os
import requests
from bs4 import BeautifulSoup
import json
import easyocr
import numpy as np
import re
from PIL import Image, ImageEnhance, ImageOps
from pdf2image import convert_from_path

# --- Configuration & Paths ---
if os.environ.get('GITHUB_ACTIONS'):
    POPPLER_PATH = None
else:
    POPPLER_PATH = r'D:\Projects\Release-24.02.0-0\poppler-24.02.0\Library\bin'

BASE_URL = "https://www.butex.edu.bd/affiliated-colleges/"
reader = easyocr.Reader(['en'], gpu=False)

def decode_roll(roll):
    """১০ এবং ১১ ডিজিট রোলের জন্য আপনার দেওয়া স্পেসিফিক লজিক"""
    roll = str(roll).strip().upper()
    batch, college, dept = "Unknown", "Unknown", "Unknown"
    
    # ১১ ডিজিট (উদা: 22070401019)
    if len(roll) == 11 and roll.isdigit():
        batch = roll[0:2]
        col_code = roll[2:4]
        dept_code = roll[4:6]
        colleges = {"02":"Pabna","03":"Chattogram","04":"Barishal","05":"Noakhali","06":"Jhenaidah","07":"TTEC","08":"NTEC","09":"Rangpur","10":"Gopalganj","11":"Jamalpur","12":"Madaripur","13":"Sylhet"}
        depts = {"01":"Yarn", "02":"Fabric", "03":"Wet Process", "04":"Apparel"}
        college, dept = colleges.get(col_code, "Unknown"), depts.get(dept_code, "Unknown")
        
    # ১০ ডিজিট (উদা: B201614001)
    elif len(roll) == 10 and roll[0].isalpha():
        col_char = roll[0]
        batch = roll[3:5] # ২০১৬ এর ১৬
        dept_code = roll[6]
        colleges = {"Z":"Chattogram","N":"Noakhali","P":"Pabna","B":"Barisal","J":"Jhenaidah","R":"Rangpur","G":"Gopalganj","T":"TTEC","S":"NTEC"}
        depts = {"1":"Yarn", "2":"Fabric", "3":"Wet Process", "4":"Apparel"}
        college, dept = colleges.get(col_char, "Unknown"), depts.get(dept_code, "Unknown")

    return batch, college, dept

def enhance_for_ocr(pil_img):
    """পিডিএফ-এর হালকা লেখাকে গাঢ় করার জন্য প্রসেসিং"""
    gray = ImageOps.grayscale(pil_img)
    return np.array(ImageEnhance.Contrast(gray).enhance(3.5))

def get_precise_data(pdf_path):
    """নতুন পিডিএফ ফরম্যাট অনুযায়ী Name, Term GPA এবং CGPA এক্সট্রাকশন"""
    results = []
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=POPPLER_PATH)
        for page in pages:
            img = enhance_for_ocr(page)
            # detail=1 দিলে টেক্সটের পজিশন পাওয়া যায়, যা দিয়ে কলাম বোঝা সহজ
            ocr_results = reader.readtext(img)
            
            full_text = " ".join([res[1] for res in ocr_results])
            # Regex: রোল (১০/১১) এরপর নাম (টেক্সট) এরপর জিপিএ (সংখ্যা)
            # এটি আপনার শেয়ার করা পিডিএফ-এর কলাম ফরম্যাট অনুযায়ী কাজ করবে
            patterns = re.findall(r'([A-Z]?\d{9,11})\s+([A-Z\.\s\-]+)\s+(\d\.\d{2})\s+(\d\.\d{2})', full_text)
            
            for roll, name, term_gpa, cgpa in patterns:
                results.append({
                    "roll": roll.strip(),
                    "name": name.strip(),
                    "term_gpa": float(term_gpa),
                    "cgpa": float(cgpa)
                })
    except Exception as e:
        print(f"  OCR Error: {e}")
    return results

def main():
    print("🚀 Precise AI Scraper starting with your PDF logic...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    master_data = {}

    if os.path.exists("data.json"):
        with open("data.json", "r", encoding='utf-8') as f:
            master_data = json.load(f)

    # Scrape settings
    res = requests.get(BASE_URL, headers=headers, timeout=15)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    for link in soup.find_all('a', href=True):
        title = link.get_text().strip().upper()
        if "RESULT" in title:
            post_url = link['href']
            # Term extraction (L2T2, L3T1 etc)
            t_match = re.search(r'LEVEL[- ]?(\d).*?TERM[- ]?(\d|I+)', title)
            term_key = f"L{t_match.group(1)}T{1 if t_match.group(2)=='I' else (2 if t_match.group(2)=='II' else t_match.group(2))}" if t_match else "LXTX"

            print(f"Scanning: {title[:40]}")
            post_res = requests.get(post_url, headers=headers)
            pdf_soup = BeautifulSoup(post_res.text, 'html.parser')
            
            for pdf_link in pdf_soup.find_all('a', href=True):
                if ".pdf" in pdf_link['href'].lower():
                    pdf_data = requests.get(pdf_link['href']).content
                    with open("temp.pdf", "wb") as f: f.write(pdf_data)
                    
                    extracted = get_precise_data("temp.pdf")
                    for item in extracted:
                        roll = item['roll']
                        if roll not in master_data:
                            b, col, d = decode_roll(roll)
                            master_data[roll] = {"name": item['name'], "batch": b, "college": col, "dept": d, "results": {}}
                        
                        # নাম Unknown থাকলে আপডেট করা
                        if master_data[roll]["name"] == "Unknown": master_data[roll]["name"] = item['name']
                        
                        master_data[roll]["results"][term_key] = item['term_gpa']
                        # CGPA আপডেট (লেটেস্টটা থাকবে)
                        master_data[roll]["cgpa"] = item['cgpa']

            # Save after each PDF
            with open("data.json", "w", encoding='utf-8') as f:
                json.dump(master_data, f, indent=4)

    if os.path.exists("temp.pdf"): os.remove("temp.pdf")
    print(f"✅ Scraping Complete. Found {len(master_data)} students.")

if __name__ == "__main__":
    main()
