#!/usr/bin/env python3
"""
NSE Financial Reports Scraper - Fixed for 403 errors
Downloads financial reports from African Financials for NSE-listed companies
"""

import requests
from bs4 import BeautifulSoup
import os
import time
import re
from pathlib import Path
import json
from datetime import datetime
import random

class NSEReportsScraper:
    def __init__(self, base_dir="reports"):
        self.nse_url = "https://afx.kwayisi.org/nse/"
        self.africanfinancials_base = "https://africanfinancials.com/company/ke-"
        self.base_dir = base_dir
        
        # Configure session with Tor proxy
        self.session = requests.Session()
        self.session.proxies = {
            'http': 'socks5h://127.0.0.1:9050',
            'https': 'socks5h://127.0.0.1:9050'
        }
        
        # === ENHANCED HEADERS to bypass 403 ===
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'DNT': '1'
        })
        
        # Create base directory
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        
        print("🔐 Configured Tor proxy at 127.0.0.1:9050", flush=True)
    
    def get_tickers(self):
        """Fetch all tickers from NSE listing page"""
        print(f"\n{'='*70}")
        print("STEP 1: Fetching NSE tickers")
        print(f"{'='*70}")
        print(f"URL: {self.nse_url}", flush=True)
        
        try:
            response = self.session.get(self.nse_url, timeout=60)
            print(f"✓ Response: {response.status_code}", flush=True)
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            ticker_list_div = soup.find('div', class_='t')
            
            if not ticker_list_div:
                print("✗ Div with class='t' (containing ticker list) not found.", flush=True)
                return []
                
            table = ticker_list_div.find('table')
            
            if not table:
                print("✗ Ticker list table not found inside div.t", flush=True)
                return []
            
            print("✓ Found the 'Listed companies/securities' table.", flush=True)
            
            tickers = []
            
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
            else:
                rows = table.find_all('tr')
            
            if rows:
                data_rows = [row for row in rows if not row.find('th')]
                if data_rows:
                    print(f"  Debug - First data row HTML: {str(data_rows[0])[:200]}...", flush=True)

            for idx, row in enumerate(rows):
                if row.find('th'):
                    continue
                
                cells = row.find_all('td')
                
                if len(cells) > 0:
                    link = cells[0].find('a')
                    if link:
                        ticker = link.text.strip()
                        if ticker and len(ticker) > 1 and len(ticker) < 10:
                            tickers.append(ticker)

            
            print(f"✓ Found {len(tickers)} tickers")
            if tickers:
                print(f"  First 5: {', '.join(tickers[:5])}")
            
            return tickers
            
        except Exception as e:
            print(f"✗ Error: {e}", flush=True)
            return []
    
    def get_tab_id(self, ticker, retry_count=3):
        """Get Documents & Reports tab ID for a company with retry logic"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/"
        
        for attempt in range(retry_count):
            try:
                # Add delay between retries
                if attempt > 0:
                    wait_time = random.uniform(3, 7)
                    print(f"    ⏳ Retry {attempt + 1}/{retry_count} after {wait_time:.1f}s...", flush=True)
                    time.sleep(wait_time)
                
                # Update Referer for this specific request
                headers = {
                    'Referer': 'https://africanfinancials.com/kenya/'
                }
                
                response = self.session.get(url, timeout=60, headers=headers)
                
                if response.status_code == 403:
                    print(f"  ⚠ 403 Forbidden (attempt {attempt + 1}/{retry_count})", flush=True)
                    
                    # Rotate Tor identity if possible
                    if attempt < retry_count - 1:
                        self._rotate_tor_identity()
                    continue
                
                if response.status_code != 200:
                    print(f"  ✗ Failed to load company page ({response.status_code})", flush=True)
                    continue
                
                soup = BeautifulSoup(response.content, 'lxml')
                
                # Search for Documents & Reports tab
                for link in soup.find_all('a'):
                    if 'Documents & Reports' in link.get_text(strip=True):
                        href = link.get('href', '')
                        if '#tab-' in href:
                            return href.split('#')[1]
                
                return None
                
            except Exception as e:
                print(f"  ✗ Tab ID error (attempt {attempt + 1}): {e}", flush=True)
                if attempt < retry_count - 1:
                    time.sleep(random.uniform(2, 5))
        
        return None
    
    def _rotate_tor_identity(self):
        """Attempt to rotate Tor identity (requires control port)"""
        try:
            from stem import Signal
            from stem.control import Controller
            
            with Controller.from_port(port=9051) as controller:
                controller.authenticate()
                controller.signal(Signal.NEWNYM)
                print("    🔄 Rotated Tor identity", flush=True)
                time.sleep(5)  # Wait for new circuit
        except ImportError:
            print("    ℹ Install 'stem' package for Tor identity rotation: pip install stem", flush=True)
        except Exception as e:
            print(f"    ⚠ Could not rotate Tor identity: {e}", flush=True)
    
    def get_documents(self, ticker, tab_id):
        """Get list of documents for a ticker"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/#{tab_id}"
        
        try:
            response = self.session.get(url, timeout=60)
            soup = BeautifulSoup(response.content, 'lxml')
            
            tab_content_div = soup.find('div', id=tab_id)
            if not tab_content_div:
                print(f"  ✗ Documents tab content div #{tab_id} not found.")
                return []
            
            reports_table = None
            for table in tab_content_div.find_all('table'):
                if table.find('th', string=re.compile(r'(Type|Year)', re.I)):
                    reports_table = table
                    break
                    
            if not reports_table:
                print("  ✗ Financial reports table not found within the tab content.")
                return []
            
            documents = []
            rows = reports_table.find_all('tr')
            
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    link = cells[0].find('a')
                    if link:
                        doc_url = link.get('href')
                        doc_type = link.get_text(strip=True)
                        year = cells[1].get_text(strip=True)
                        period = cells[2].get_text(strip=True)
                        date = cells[3].get_text(strip=True)
                        
                        match = re.search(r'/document/(ke-[^/]+)/', doc_url)
                        if match:
                            full_name = match.group(1)
                            filename = re.sub(f'^ke-{ticker.lower()}-', '', full_name)
                            
                            documents.append({
                                'url': doc_url,
                                'type': doc_type,
                                'year': year,
                                'period': period,
                                'date': date,
                                'filename': filename
                            })
            
            return documents
            
        except Exception as e:
            print(f"  ✗ Documents error: {e}", flush=True)
            return []
    
    def get_pdf_url(self, doc_url):
        """Extract Google Drive PDF URL from document page"""
        try:
            response = self.session.get(doc_url, timeout=60)
            soup = BeautifulSoup(response.content, 'lxml')
            
            iframe = soup.find('iframe', src=re.compile(r'drive\.google\.com'))
            if iframe:
                src = iframe.get('src')
                match = re.search(r'/d/([^/]+)/', src)
                if match:
                    file_id = match.group(1)
                    return f"https://drive.google.com/uc?export=download&id={file_id}"
            
            return None
            
        except Exception as e:
            print(f"      ✗ PDF URL error: {e}", flush=True)
            return None
    
    def download_pdf(self, pdf_url, output_path):
        """Download PDF file"""
        try:
            response = self.session.get(pdf_url, stream=True, timeout=120)
            
            if 'text/html' in response.headers.get('Content-Type', ''):
                soup = BeautifulSoup(response.content, 'lxml')
                link = soup.find('a', id='uc-download-link')
                if link:
                    confirm_url = link.get('href')
                    if not confirm_url.startswith('http'):
                        confirm_url = 'https://drive.google.com' + confirm_url
                    response = self.session.get(confirm_url, stream=True, timeout=120)
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            size_kb = os.path.getsize(output_path) / 1024
            print(f"      ✓ {size_kb:.1f} KB", flush=True)
            return True
            
        except Exception as e:
            print(f"      ✗ Download error: {e}", flush=True)
            return False
    
    def process_ticker(self, ticker):
        """Process all documents for one ticker"""
        print(f"\n{'='*70}")
        print(f"Processing: {ticker}")
        print(f"{'='*70}")
        
        ticker_dir = Path(self.base_dir) / ticker.upper()
        ticker_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"  → Getting tab ID...")
        tab_id = self.get_tab_id(ticker)
        
        if not tab_id:
            print(f"  ✗ No Documents & Reports tab found")
            return 0
        
        print(f"    ✓ Tab: {tab_id}")
        
        print(f"  → Fetching documents...")
        documents = self.get_documents(ticker, tab_id)
        
        if not documents:
            print(f"  ✗ No documents found")
            return 0
        
        print(f"    ✓ Found {len(documents)} documents")
        
        downloaded = 0
        
        for i, doc in enumerate(documents, 1):
            print(f"\n  [{i}/{len(documents)}] {doc['type']} {doc['year']} {doc['period']}")
            
            pdf_filename = f"{doc['filename']}.pdf"
            pdf_path = ticker_dir / pdf_filename
            
            if pdf_path.exists():
                print(f"      ⊙ Already exists")
                continue
            
            print(f"      → Extracting PDF URL...")
            pdf_url = self.get_pdf_url(doc['url'])
            
            if not pdf_url:
                print(f"      ✗ No PDF found")
                continue
            
            print(f"      → Downloading...")
            if self.download_pdf(pdf_url, pdf_path):
                metadata = {
                    'ticker': ticker,
                    'type': doc['type'],
                    'year': doc['year'],
                    'period': doc['period'],
                    'date': doc['date'],
                    'source_url': doc['url'],
                    'downloaded_at': datetime.now().isoformat()
                }
                
                json_path = ticker_dir / f"{doc['filename']}.json"
                with open(json_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                downloaded += 1
            
            time.sleep(random.uniform(1, 3))  # Random delay
        
        print(f"\n  ✓ Downloaded {downloaded} new files")
        return downloaded
    
    def run(self, test_mode=False):
        """Main execution"""
        start_time = datetime.now()
        
        print("\n" + "🚀 " * 35)
        print("NSE FINANCIAL REPORTS SCRAPER")
        print("🚀 " * 35)
        print(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Output: {os.path.abspath(self.base_dir)}")
        print("=" * 70, flush=True)
        
        tickers = self.get_tickers()
        
        if not tickers:
            print("\n✗ No tickers found. Exiting.")
            return
        
        if test_mode:
            tickers = tickers[:3]
            print(f"\n🧪 TEST MODE: Processing only {len(tickers)} tickers")
        
        print(f"\n📊 Will process {len(tickers)} tickers\n")
        
        total_downloaded = 0
        successful_tickers = 0
        
        for i, ticker in enumerate(tickers, 1):
            print(f"\n[{i}/{len(tickers)}]")
            
            try:
                downloaded = self.process_ticker(ticker)
                total_downloaded += downloaded
                successful_tickers += 1
            except Exception as e:
                print(f"✗ Critical error for {ticker}: {e}", flush=True)
            
            if i < len(tickers):
                time.sleep(random.uniform(2, 5))
        
        end_time = datetime.now()
        duration = end_time - start_time
        
        print("\n" + "=" * 70)
        print("SCRAPING COMPLETE")
        print("=" * 70)
        print(f"Tickers processed: {successful_tickers}/{len(tickers)}")
        print(f"Files downloaded: {total_downloaded}")
        print(f"Duration: {duration}")
        print(f"Output: {self.base_dir}/")
        print("=" * 70 + "\n")
        
        summary = {
            'scrape_date': datetime.now().isoformat(),
            'duration_seconds': duration.total_seconds(),
            'tickers_processed': successful_tickers,
            'total_tickers': len(tickers),
            'files_downloaded': total_downloaded,
            'test_mode': test_mode
        }
        
        summary_path = Path(self.base_dir) / 'scrape_summary.json'
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"✓ Summary saved to {summary_path}\n")

def main():
    import sys
    
    test_mode = '--test' in sys.argv or os.getenv('TEST_MODE') == 'true'
    
    scraper = NSEReportsScraper(base_dir="reports")
    scraper.run(test_mode=test_mode)

if __name__ == "__main__":
    main()
