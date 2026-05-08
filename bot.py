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
    POPPLER_PATH = None  # GitHub handles this automatically
else:
    # Your Local PC Path
    POPPLER_PATH = r'D:\Projects\Release-24.02.0-0\poppler-24.02.0\Library\bin'

BASE_URL = "https://www.butex.edu.bd/affiliated-colleges/"
MAX_PAGES = 30 

# Initialize EasyOCR (English) - runs on CPU
reader = easyocr.Reader(['en'], gpu=False)

def decode_roll(roll):
    """Roll mapping for Batch, College and Dept"""
    roll = str(roll).strip().upper()
    batch, college, dept = "Unknown", "Unknown", "Unknown"
    
    # 11-digit format
    if len(roll) == 11 and roll.isdigit():
        batch = roll[0:2]          
        college_code = roll[2:4]   
        dept_code = roll[4:6]      
        colleges = {"02":"Pabna","03":"Chattogram","04":"Barishal","05":"Noakhali","06":"Jhenaidah","07":"TTEC/BTEC","08":"NTEC/BHETI","09":"Rangpur","10":"Gopalganj","11":"Jamalpur","12":"Madaripur","13":"Sylhet"}
        college = colleges.get(college_code, "Unknown")
        depts = {"01":"Yarn", "02":"Fabric", "03":"Wet Process", "04":"Apparel"}
        dept = depts.get(dept_code, "Unknown")
        
    # Alpha-Numeric format
    elif len(roll) == 10 and roll[0].isalpha():
        college_code = roll[0]     
        batch = roll[3:5]     
        dept_code = roll[5:7]      
        colleges = {"Z":"Chattogram","N":"Noakhali","P":"Pabna","B":"Barisal","J":"Jhenaidah","R":"Rangpur","G":"Gopalganj","T":"TTEC/BTEC","S":"NTEC/BHETI"}
        college = colleges.get(college_code, "Unknown")
        depts = {"11":"Yarn", "12":"Fabric", "13":"Wet Process", "14":"Apparel"}
        dept = depts.get(dept_code, "Unknown")

    return batch, college, dept

def enhance_for_ocr(pil_img):
    """Magic function to make light text bold and dark"""
    gray = ImageOps.grayscale(pil_img)
    enhancer = ImageEnhance.Contrast(gray)
    enhanced = enhancer.enhance(3.5)
    sharpener = ImageEnhance.Sharpness(enhanced)
    return np.array(sharpener.enhance(2.5))

def get_data_easyocr(pdf_path):
    """AI based data extraction"""
    results = []
    try:
        pages = convert_from_path(pdf_path, 300, poppler_path=POPPLER_PATH)
        for page in pages:
            processed_img = enhance_for_ocr(page)
            ocr_results = reader.readtext(processed_img, detail=0)
            full_text = " ".join(ocr_results)
            
            # Pattern to catch Roll and nearby GPA
            matches = re.findall(r'([A-Z]?\d{9,11}).*?(\d\.\d{2})', full_text)
            for roll, gpa in matches:
                results.append({"roll": roll.upper(), "gpa": float(gpa)})
    except Exception as e:
        print(f"OCR Error: {e}")
    return results

def calculate_rankings(master_data):
    """Calculate College and Departmental Ranks"""
    student_list = []
    for roll, info in master_data.items():
        if info["results"]:
            # Ranking based on the latest available term GPA
            latest_term = sorted(info["results"].keys())[-1]
            gpa = info["results"][latest_term]
            student_list.append({
                "roll": roll, "gpa": gpa, "dept": info["dept"], "college": info["college"]
            })

    # Sort by GPA descending
    student_list.sort(key=lambda x: x["gpa"], reverse=True)

    college_counts = {}
    dept_counts = {}

    for student in student_list:
        r = student["roll"]
        c = student["college"]
        d = student["dept"]
        
        # College Rank
        college_counts[c] = college_counts.get(c, 0) + 1
        master_data[r]["college_rank"] = college_counters[c]
        
        # Department Rank (within that specific college)
        dept_key = f"{c}_{d}"
        dept_counts[dept_key] = dept_counts.get(dept_key, 0) + 1
        master_data[r]["dept_rank"] = dept_counts[dept_key]
        
    return master_data

def main():
    print("🚀 AI Scraper with Ranking Engine Engine Started...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    master_data = {}

    if os.path.exists("data.json"):
        with open("data.json", "r", encoding='utf-8') as f:
            master_data = json.load(f)

    # Scrape settings
    pages_to_scrape = [1] if os.environ.get('GITHUB_ACTIONS') and os.path.exists("data.json") else range(1, MAX_PAGES + 1)

    for page_num in pages_to_scrape:
        print(f"--- Checking Page {page_num} ---")
        url = BASE_URL if page_num == 1 else f"{BASE_URL}page/{page_num}/"
        
        try:
            res = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                title = link.get_text().strip()
                if "RESULT" in title.upper() or "ফলাফল" in title.upper():
                    post_url = link['href']
                    
                    # Term Key (e.g. L2T1)
                    t_match = re.search(r'LEVEL[- ]?(\d).*?TERM[- ]?(\d|I+)', title.upper())
                    term_key = "LXTX"
                    if t_match:
                        l, t = t_match.group(1), t_match.group(2)
                        term_key = f"L{l}T{1 if t=='I' else (2 if t=='II' else t)}"

                    post_res = requests.get(post_url, headers=headers)
                    pdf_soup = BeautifulSoup(post_res.text, 'html.parser')
                    for pdf_link in pdf_soup.find_all('a', href=True):
                        if '.pdf' in pdf_link['href'].lower():
                            print(f"AI Scanning: {title[:40]}...")
                            pdf_content = requests.get(pdf_link['href']).content
                            with open("temp.pdf", "wb") as f:
                                f.write(pdf_content)
                            
                            extracted = get_data_easyocr("temp.pdf")
                            for item in extracted:
                                roll = item['roll']
                                if roll not in master_data:
                                    b, c, d = decode_roll(roll)
                                    master_data[roll] = {"name": "Unknown", "batch": b, "college": c, "dept": d, "results": {}}
                                master_data[roll]["results"][term_key] = item['gpa']

            # Update rankings before saving
            master_data = calculate_rankings(master_data)
            with open("data.json", "w", encoding='utf-8') as f:
                json.dump(master_data, f, indent=4)
                
        except Exception as e:
            print(f"Error: {e}")

    if os.path.exists("temp.pdf"): os.remove("temp.pdf")
    print(f"✅ Finished. Database now has {len(master_data)} students.")

if __name__ == "__main__":
    main()
