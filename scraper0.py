import requests
from bs4 import BeautifulSoup
import os
import time
import re
from pathlib import Path
from urllib.parse import urljoin
import json
import sys
import subprocess

class NSEReportsScraper:
    def __init__(self, base_dir="reports", use_tor=True):
        self.nse_url = "https://afx.kwayisi.org/nse/"
        self.africanfinancials_base = "https://africanfinancials.com/company/ke-"
        self.base_dir = base_dir
        self.use_tor = use_tor
        self.timeout = 60  # Increased timeout for Tor
        
        # Setup session with Tor if enabled
        self.session = requests.Session()
        if use_tor:
            print("🔐 Configuring Tor proxy...", flush=True)
            try:
                # Use PySocks for SOCKS5 proxy support
                self.session.proxies = {
                    'http': 'socks5h://127.0.0.1:9050',
                    'https': 'socks5h://127.0.0.1:9050'
                }
                # Test if PySocks is available
                import socks
                print("✓ PySocks library loaded", flush=True)
            except ImportError:
                print("⚠️  PySocks not available, trying urllib3 approach", flush=True)
                self.use_tor = False
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
    def test_connection(self):
        """Test if Tor connection is working"""
        if not self.use_tor:
            print("ℹ️  Using direct connection (no Tor)", flush=True)
            return True
            
        print("🔍 Testing Tor connection...", flush=True)
        try:
            response = self.session.get('https://check.torproject.org/api/ip', timeout=10)
            data = response.json()
            if data.get('IsTor'):
                print(f"✓ Connected via Tor (IP: {data.get('IP')})", flush=True)
                return True
            else:
                print(f"✗ Not using Tor (IP: {data.get('IP')})", flush=True)
                return False
        except Exception as e:
            print(f"✗ Tor connection test failed: {e}", flush=True)
            print("   Trying to continue anyway...", flush=True)
            return False
        
    def get_tickers(self):
        """Scrape all tickers from NSE page"""
        print("\n" + "=" * 70, flush=True)
        print("STEP 1: Fetching tickers from NSE...", flush=True)
        print(f"URL: {self.nse_url}", flush=True)
        print("=" * 70, flush=True)
        
        try:
            response = self.session.get(self.nse_url, timeout=self.timeout)
            print(f"✓ Response received: {response.status_code}", flush=True)
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            tickers = []
            table = soup.find('table')
            
            if not table:
                print("✗ No table found on page", flush=True)
                return []
            
            # Try to find tbody first
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
            else:
                # If no tbody, get all tr elements directly from table
                rows = table.find_all('tr')
            
            print(f"✓ Found {len(rows)} rows in table", flush=True)
            
            # Skip header row if it exists
            for row in rows:
                # Check if this is a header row
                if row.find('th'):
                    continue
                    
                tds = row.find_all('td')
                if not tds:
                    continue
                
                # First td should contain the ticker link
                first_td = tds[0]
                link = first_td.find('a')
                
                if link:
                    ticker = link.text.strip()
                    if ticker:  # Make sure ticker is not empty
                        tickers.append(ticker)
                        print(f"  Found: {ticker}", flush=True)
            
            print(f"\n✓ Successfully extracted {len(tickers)} tickers", flush=True)
            if tickers:
                print(f"Sample tickers: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}\n", flush=True)
            return tickers
            
        except requests.Timeout:
            print(f"✗ TIMEOUT: Could not reach {self.nse_url} within {self.timeout}s", flush=True)
            return []
        except Exception as e:
            print(f"✗ ERROR: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return []
    
    def get_documents_tab_id(self, ticker):
        """Get the unique tab ID for Documents & Reports section"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/"
        print(f"  → Fetching tab ID...", flush=True)
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            print(f"    Status: {response.status_code}", flush=True)
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the Documents & Reports tab
            tabs = soup.find_all('a', class_='tab-link')
            for tab in tabs:
                if 'Documents & Reports' in tab.get_text():
                    href = tab.get('href', '')
                    if href.startswith('#tab-'):
                        tab_id = href[1:]  # Remove the '#'
                        print(f"    ✓ Tab ID: {tab_id}", flush=True)
                        return tab_id
            
            print(f"    ✗ No Documents & Reports tab found", flush=True)
            return None
            
        except requests.Timeout:
            print(f"    ✗ TIMEOUT after {self.timeout}s", flush=True)
            return None
        except Exception as e:
            print(f"    ✗ ERROR: {e}", flush=True)
            return None
    
    def get_document_links(self, ticker, tab_id):
        """Get all document links from the Documents & Reports tab"""
        url = f"{self.africanfinancials_base}{ticker.lower()}/#{tab_id}"
        print(f"  → Fetching documents list", flush=True)
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            documents = []
            table = soup.find('table', id='af21_prices')
            
            if not table:
                print(f"    ✗ No documents table found", flush=True)
                return documents
            
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
                print(f"    ✓ Found {len(rows)} documents", flush=True)
                
                for row in rows:
                    tds = row.find_all('td')
                    if len(tds) >= 4:
                        # Get the first link in the row
                        link_tag = tds[0].find('a')
                        if link_tag:
                            doc_url = link_tag.get('href')
                            doc_type = link_tag.get_text(strip=True).replace('\n', ' ')
                            
                            year = tds[1].get_text(strip=True)
                            period = tds[2].get_text(strip=True)
                            date = tds[3].get_text(strip=True)
                            
                            # Extract filename from URL
                            match = re.search(r'/document/(ke-[^/]+)/', doc_url)
                            if match:
                                filename = match.group(1)
                                filename = filename.replace(f'ke-{ticker.lower()}-', '')
                                
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
            print(f"    ✗ ERROR: {e}", flush=True)
            return []
    
    def extract_pdf_url(self, doc_url):
        """Extract Google Drive PDF URL from document page"""
        try:
            response = self.session.get(doc_url, timeout=self.timeout)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find iframe with Google Drive link
            iframe = soup.find('iframe', {'src': re.compile(r'drive\.google\.com')})
            if iframe:
                drive_url = iframe.get('src')
                # Convert to download URL
                match = re.search(r'/d/([^/]+)/', drive_url)
                if match:
                    file_id = match.group(1)
                    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                    return download_url
            
            return None
            
        except Exception as e:
            print(f"      ✗ Error extracting PDF URL: {e}", flush=True)
            return None
    
    def download_pdf(self, pdf_url, output_path):
        """Download PDF from Google Drive"""
        try:
            print(f"      Downloading...", flush=True)
            
            # First request
            response = self.session.get(pdf_url, stream=True, timeout=60)
            
            # Handle Google Drive's virus scan warning
            if 'text/html' in response.headers.get('Content-Type', ''):
                soup = BeautifulSoup(response.content, 'html.parser')
                download_link = soup.find('a', {'id': 'uc-download-link'})
                if download_link:
                    confirm_url = download_link.get('href')
                    if not confirm_url.startswith('http'):
                        confirm_url = 'https://drive.google.com' + confirm_url
                    response = self.session.get(confirm_url, stream=True, timeout=60)
            
            # Save file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            file_size = os.path.getsize(output_path) / 1024  # KB
            print(f"      ✓ Downloaded ({file_size:.1f} KB)", flush=True)
            return True
            
        except Exception as e:
            print(f"      ✗ Download failed: {e}", flush=True)
            return False
    
    def scrape_ticker(self, ticker):
        """Scrape all documents for a single ticker"""
        print(f"\n{'='*70}")
        print(f"Processing: {ticker}")
        print(f"{'='*70}")
        
        # Create ticker directory
        ticker_dir = Path(self.base_dir) / ticker.upper()
        ticker_dir.mkdir(parents=True, exist_ok=True)
        
        # Get documents tab ID
        tab_id = self.get_documents_tab_id(ticker)
        if not tab_id:
            print(f"  ⊗ Skipping - no documents tab\n", flush=True)
            return
        
        # Get document links
        documents = self.get_document_links(ticker, tab_id)
        if not documents:
            print(f"  ⊗ No documents found\n", flush=True)
            return
        
        # Download each document
        downloaded = 0
        for i, doc in enumerate(documents, 1):
            print(f"\n  [{i}/{len(documents)}] {doc['type']} - {doc['year']} {doc['period']}", flush=True)
            
            output_filename = f"{doc['filename']}.pdf"
            output_path = ticker_dir / output_filename
            
            if output_path.exists():
                print(f"      ⊙ Already exists, skipping", flush=True)
                continue
            
            # Extract PDF URL
            pdf_url = self.extract_pdf_url(doc['url'])
            if not pdf_url:
                continue
            
            # Download PDF
            if self.download_pdf(pdf_url, output_path):
                # Save metadata
                metadata = {
                    'ticker': ticker,
                    'type': doc['type'],
                    'year': doc['year'],
                    'period': doc['period'],
                    'date': doc['date'],
                    'source_url': doc['url']
                }
                metadata_path = ticker_dir / f"{doc['filename']}.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                downloaded += 1
            
            time.sleep(1)  # Be nice to servers
        
        print(f"\n  ✓ Downloaded {downloaded} new files for {ticker}", flush=True)
    
    def run(self, specific_tickers=None, max_tickers=None):
        """Run the scraper"""
        print("\n" + "🚀 " * 35)
        print("NSE Financial Reports Scraper")
        print("🚀 " * 35, flush=True)
        
        # Test connection if using Tor
        if self.use_tor:
            self.test_connection()
        
        # Get tickers
        tickers = specific_tickers if specific_tickers else self.get_tickers()
        
        if not tickers:
            print("\n✗ No tickers found. Exiting.", flush=True)
            return
        
        # Limit tickers for testing
        if max_tickers:
            tickers = tickers[:max_tickers]
            print(f"⚠️  Limiting to first {max_tickers} tickers for testing\n", flush=True)
        
        print(f"\n📊 Processing {len(tickers)} tickers...", flush=True)
        print(f"📁 Output directory: {self.base_dir}\n", flush=True)
        
        successful = 0
        for i, ticker in enumerate(tickers, 1):
            print(f"\n[{i}/{len(tickers)}]", flush=True)
            try:
                self.scrape_ticker(ticker)
                successful += 1
            except Exception as e:
                print(f"✗ Critical error for {ticker}: {e}", flush=True)
                import traceback
                traceback.print_exc()
            
            # Delay between tickers
            if i < len(tickers):
                time.sleep(2)
        
        print("\n" + "=" * 70)
        print(f"✓ Scraping completed!")
        print(f"  Processed: {successful}/{len(tickers)} tickers")
        print(f"  Output: {self.base_dir}/")
        print("=" * 70 + "\n", flush=True)

if __name__ == "__main__":
    # Check if running in test mode
    import sys
    test_mode = '--test' in sys.argv or os.getenv('TEST_MODE') == 'true'
    
    scraper = NSEReportsScraper(use_tor=True)
    
    if test_mode:
        print("🧪 Running in TEST MODE (first 3 tickers only)\n")
        scraper.run(max_tickers=3)
    else:
        scraper.run()
