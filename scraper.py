"""
NSE Financial Reports Scraper
Downloads financial reports from African Financials for NSE-listed companies
"""

import requests # Kept for potential future use, though not used for fetching now
from bs4 import BeautifulSoup
import os
import time
import re
import argparse
from pathlib import Path
import json
from datetime import datetime
from curl_cffi import requests as cffi_requests # <--- NEW IMPORT

class NSEReportsScraper:
    def __init__(self, base_dir="reports"):
        self.nse_url = "https://afx.kwayisi.org/nse/"
        self.africanfinancials_base = "https://africanfinancials.com/company/ke-"
        self.base_dir = base_dir
        
        # Define proxies in the format curl_cffi expects (socks5://host:port)
        self.cffi_proxies = {
            'http': 'socks5://127.0.0.1:9050',
            'https': 'socks5://127.0.0.1:9050'
        }
        
        # === FIX: Headers for curl_cffi (applied directly in method calls) ===
        self.cffi_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://africanfinancials.com/kenya/',
            'Connection': 'keep-alive',
            'Cache-Control': 'max-age=0',
            'DNT': '1' 
        }
        # ========================================================================
        
        # Create base directory
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        
        print("🔐 Configured Tor proxy at 127.0.0.1:9050", flush=True)

    def get_ticker_batch(self, batch_number, batch_size=10):
        """
        Get a specific batch of tickers.
        batch_number: 1-based batch number (1, 2, 3, etc.)
        batch_size: number of tickers per batch (default 10)
        """
        # Get all tickers first
        all_tickers = self.get_tickers()
        
        if not all_tickers:
            return []
    
        # Calculate batch indices
        start_idx = (batch_number - 1) * batch_size
        end_idx = start_idx + batch_size
        
        # Get batch
        batch_tickers = all_tickers[start_idx:end_idx]
        
        print(f"\n{'='*70}")
        print(f"BATCH MODE: Processing Batch {batch_number}")
        print(f"Tickers {start_idx + 1}-{min(end_idx, len(all_tickers))} of {len(all_tickers)}")
        print(f"Batch tickers: {', '.join(batch_tickers)}")
        print(f"{'='*70}\n")
        
        return batch_tickers
        
    def _make_cffi_request(self, url, stream=False, timeout=60):
        """Helper to make a curl-cffi request with impersonation and proxies"""
        time.sleep(0.1) # 0.1-second delay between requests
        return cffi_requests.get(
            url, 
            headers=self.cffi_headers,
            proxies=self.cffi_proxies, 
            impersonate="chrome120", # Bypass TLS fingerprinting
            stream=stream,
            timeout=timeout
        )

    def get_tickers(self):
        """Fetch all tickers from NSE listing page"""
        print(f"\n{'='*70}")
        print("STEP 1: Fetching NSE tickers")
        print(f"{'='*70}")
        print(f"URL: {self.nse_url}", flush=True)
        
        try:
            # FIX: Use _make_cffi_request
            response = self._make_cffi_request(self.nse_url)
            print(f"✓ Response: {response.status_code}", flush=True)
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # FIX: Target the correct table inside div.t
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
    
    def get_tab_id(self, ticker):
        """Get Documents & Reports tab ID for a company"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/"
        
        try:
            # FIX: Use _make_cffi_request
            response = self._make_cffi_request(url)
            
            if response.status_code != 200:
                print(f"  ✗ Failed to load company page ({response.status_code})", flush=True)
                return None
            
            soup = BeautifulSoup(response.content, 'lxml')
            
            # FIX: search for ANY <a> tag containing the required text.
            for link in soup.find_all('a'):
                if 'Documents & Reports' in link.get_text(strip=True):
                    href = link.get('href', '')
                    if '#tab-' in href:
                        return href.split('#')[1]
            
            return None
            
        except Exception as e:
            print(f"  ✗ Tab ID error: {e}", flush=True)
            return None
    
    def get_documents(self, ticker, tab_id):
        """Get list of documents for a ticker"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/#{tab_id}"
        
        try:
            # FIX: Use _make_cffi_request
            response = self._make_cffi_request(url)
            soup = BeautifulSoup(response.content, 'lxml')
            
            # FIX: Find the reports table based on its headers.
            tab_content_div = soup.find('div', id=tab_id)
            if not tab_content_div:
                print(f"  ✗ Documents tab content div #{tab_id} not found.")
                return []
            
            reports_table = None
            for table in tab_content_div.find_all('table'):
                # Check for a header row containing 'Type' or 'Year'
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
                        
                        # Extract filename
                        match = re.search(r'/document/(ke-[^/]+)/', doc_url)
                        if match:
                            full_name = match.group(1)
                            # Remove ke-ticker- prefix
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
            # FIX: Use _make_cffi_request
            response = self._make_cffi_request(doc_url)
            soup = BeautifulSoup(response.content, 'lxml')
            
            # Find Google Drive iframe
            iframe = soup.find('iframe', src=re.compile(r'drive\.google\.com'))
            if iframe:
                src = iframe.get('src')
                # Extract file ID
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
            # FIX: Use _make_cffi_request with stream=True
            response = self._make_cffi_request(pdf_url, stream=True, timeout=120)
            
            # Handle Google Drive virus scan page
            if 'text/html' in response.headers.get('Content-Type', ''):
                soup = BeautifulSoup(response.content, 'lxml')
                link = soup.find('a', id='uc-download-link')
                if link:
                    confirm_url = link.get('href')
                    if not confirm_url.startswith('http'):
                        confirm_url = 'https://drive.google.com' + confirm_url
                    
                    # FIX: Use _make_cffi_request for the confirmation URL
                    response = self._make_cffi_request(confirm_url, stream=True, timeout=120)
            
            # Write file
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
        
        # Create ticker directory
        ticker_dir = Path(self.base_dir) / ticker.upper()
        ticker_dir.mkdir(parents=True, exist_ok=True)
        
        # Get tab ID
        print(f"  → Getting tab ID...")
        tab_id = self.get_tab_id(ticker)
        
        if not tab_id:
            print(f"  ✗ No Documents & Reports tab found")
            return 0
        
        print(f"    ✓ Tab: {tab_id}")
        
        # Get documents list
        print(f"  → Fetching documents...")
        documents = self.get_documents(ticker, tab_id)
        
        if not documents:
            print(f"  ✗ No documents found")
            return 0
        
        print(f"    ✓ Found {len(documents)} documents")
        
        # Download each document
        downloaded = 0
        
        for i, doc in enumerate(documents, 1):
            print(f"\n  [{i}/{len(documents)}] {doc['type']} {doc['year']} {doc['period']}")
            
            pdf_filename = f"{doc['filename']}.pdf"
            pdf_path = ticker_dir / pdf_filename
            
            # Skip if exists
            if pdf_path.exists():
                print(f"      ⊙ Already exists")
                continue
            
            # Get PDF URL
            print(f"      → Extracting PDF URL...")
            pdf_url = self.get_pdf_url(doc['url'])
            
            if not pdf_url:
                print(f"      ✗ No PDF found")
                continue
            
            # Download
            print(f"      → Downloading...")
            if self.download_pdf(pdf_url, pdf_path):
                # Save metadata
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
            
            # Note: A 0.1-second sleep is already applied in _make_cffi_request
            
        print(f"\n  ✓ Downloaded {downloaded} new files")
        return downloaded
    
    def run(self, test_mode=False, batch_number=None, batch_size=10):
        """Main execution"""
        start_time = datetime.now()
        
        print("\n" + "🚀 " * 35)
        print("NSE FINANCIAL REPORTS SCRAPER")
        print("🚀 " * 35)
        print(f"Start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Output: {os.path.abspath(self.base_dir)}")
        print("=" * 70, flush=True)
        
        # Get tickers (batch mode or all)
        if batch_number:
            tickers = self.get_ticker_batch(batch_number, batch_size)
            if not tickers:
                print(f"\n✗ No tickers found for batch {batch_number}. Exiting.")
                return
        else:
            tickers = self.get_tickers()
            if not tickers:
                print("\n✗ No tickers found. Exiting.")
                return
            
            # Test mode - limit to 3 tickers
            if test_mode:
                tickers = tickers[:3]
                print(f"\n🧪 TEST MODE: Processing only {len(tickers)} tickers")
        
        print(f"\n📊 Will process {len(tickers)} tickers\n")
        
        # Process each ticker
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
            
            # Pause between tickers
            if i < len(tickers):
                time.sleep(0.1) # Existing 0.1-second delay between full ticker cycles
        
        # Summary
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
        
        # Save summary
        summary = {
            'scrape_date': datetime.now().isoformat(),
            'duration_seconds': duration.total_seconds(),
            'tickers_processed': successful_tickers,
            'total_tickers': len(tickers),
            'files_downloaded': total_downloaded,
            'test_mode': test_mode,
            'batch_number': batch_number if batch_number else 'all',
            'batch_size': batch_size if batch_number else 'N/A'
        }
        
        summary_path = Path(self.base_dir) / 'scrape_summary.json'
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"✓ Summary saved to {summary_path}\n")

def main():
    import sys
    
    # Parse arguments
    parser = argparse.ArgumentParser(description='NSE Financial Reports Scraper')
    parser.add_argument('--test', action='store_true', help='Test mode (process only 3 tickers)')
    parser.add_argument('--batch', type=int, default=None, help='Batch number to process (1-7)')
    parser.add_argument('--batch-size', type=int, default=10, help='Number of tickers per batch')
    
    args = parser.parse_args()
    
    # Check for test mode from args or environment
    test_mode = args.test or os.getenv('TEST_MODE') == 'true'
    
    scraper = NSEReportsScraper(base_dir="reports")
    scraper.run(test_mode=test_mode, batch_number=args.batch, batch_size=args.batch_size)
    
if __name__ == "__main__":
    main()
