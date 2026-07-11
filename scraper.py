from config import TARGET_AREAS

import json
import re
import time
import logging
import os
from datetime import datetime
import requests as http_requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('scraper')

class Scraper:
    def __init__(self):
        self.session = http_requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-MY,en;q=0.9',
        })

    def scrape_all(self):
        all_results = []
        for target in TARGET_AREAS:
            state = target['state']
            slug = target['slug']
            log.info(f"Scraping {state}...")
            rent = self._scrape(state, slug, 'rent')
            time.sleep(30)
            sale = self._scrape(state, slug, 'sale')
            time.sleep(30)
            combined = rent + sale
            log.info(f"  {state}: {len(rent)} rent + {len(sale)} sale = {len(combined)} total")
            all_results.extend(combined)
        return all_results

    def _scrape(self, state, slug, listing_type):
        results = self._try_propertyguru(state, slug, listing_type)
        if results:
            return results
        return self._try_iproperty(state, slug, listing_type)

    def _try_propertyguru(self, state, slug, listing_type):
        results = []
        try:
            url = f"https://www.propertyguru.com.my/property-for-{listing_type}/condo-apartment/all/{slug}"
            log.info(f"  Fetching {url}")
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                log.warning(f"  PropertyGuru returned {resp.status_code}")
                return []
            soup = BeautifulSoup(resp.text, 'html.parser')
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string)
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if isinstance(item, dict) and item.get('name'):
                            parsed = self._parse_jsonld(item, state, 'propertyguru')
                            if parsed:
                                results.append(parsed)
                except:
                    pass
            if not results:
                for sel in ['[data-testid="listing-item"]', '.listing-item', '[class*="listing"] [class*="card"]']:
                    listings = soup.select(sel)
                    if listings:
                        for el in listings:
                            parsed = self._parse_html(el, state, listing_type, 'propertyguru')
                            if parsed:
                                results.append(parsed)
                        break
        except Exception as e:
            log.error(f"  PropertyGuru error: {e}")
        return results

    def _try_iproperty(self, state, slug, listing_type):
        results = []
        try:
            url = f"https://www.iproperty.com.my/property/for-{listing_type}/condo-apartment/all/{slug}"
            log.info(f"  Fetching {url}")
            resp = self.session.get(url, timeout=30)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, 'html.parser')
            for sel in ['[class*="listing-card"]', '[class*="property-card"]', 'article[class*="listing"]']:
                listings = soup.select(sel)
                if listings:
                    for el in listings:
                        parsed = self._parse_html(el, state, listing_type, 'iproperty')
                        if parsed:
                            results.append(parsed)
                    break
        except Exception as e:
            log.error(f"  iProperty error: {e}")
        return results

    def _parse_jsonld(self, item, state, source):
        try:
            name = item.get('name', '')
            if not name or len(name) < 5:
                return None
            price = 0
            offers = item.get('offers', {})
            if isinstance(offers, dict):
                price = self._parse_price(str(offers.get('price', '')))
            size = 0
            if item.get('floorSize'):
                size = int(item.get('floorSize', {}).get('value', 0))
            if size == 0:
                m = re.search(r'([\d,]+)\s*(sqft|sq ft)', str(item), re.I)
                if m:
                    size = int(m.group(1).replace(',', ''))
            beds = 0
            if item.get('numberOfRooms'):
                beds = int(item['numberOfRooms'])
            return {'name': name[:100], 'type': 'Condominium', 'beds': beds, 'size': size if size > 0 else 900, 'price': price, 'rent': 0, 'year_built': 0, 'area': state, 'state': state, 'source': source}
        except:
            return None

    def _parse_html(self, el, state, listing_type, source):
        try:
            title_el = el.select_one('h2, h3, [class*="title"], a[class*="name"]')
            name = title_el.get_text(strip=True) if title_el else None
            if not name or len(name) < 5:
                return None
            price_el = el.select_one('[class*="price"], [data-testid*="price"]')
            price_text = price_el.get_text(strip=True) if price_el else ''
            price = self._parse_price(price_text)
            if listing_type == 'rent':
                rent = price
                price = 0
            else:
                rent = 0
            text = el.get_text(' ', strip=True)
            beds = 0
            size = 0
            prop_type = 'Condominium'
            bm = re.search(r'(\d+)\s*(?:bed|bedroom|Beds|Bedrooms)', text, re.I)
            if bm:
                beds = int(bm.group(1))
            sm = re.search(r'([\d,]+)\s*(?:sqft|sq ft|sq\. ft|ft²)', text, re.I)
            if sm:
                size = int(sm.group(1).replace(',', ''))
            tm = re.search(r'(Condominium|Apartment|Serviced Residence|Flat|Studio|Terrace|Semi-D)', text, re.I)
            if tm:
                prop_type = tm.group(1).title()
            if price == 0 and rent == 0:
                return None
            return {'name': name[:100], 'type': prop_type, 'beds': beds, 'size': size if size > 0 else 900, 'price': price, 'rent': rent, 'year_built': 0, 'area': state, 'state': state, 'source': source}
        except:
            return None

    def _parse_price(self, text):
        if not text:
            return 0
        text = re.sub(r'\s*/\s*(mo|month)', '', text, flags=re.I)
        m = re.search(r'RM\s*([\d,]+(?:\.\d+)?)', text, re.I)
        if m:
            return float(m.group(1).replace(',', ''))
        m = re.search(r'([\d,]+(?:\.\d+)?)', text)
        if m:
            v = float(m.group(1).replace(',', ''))
            if v > 100:
                return v
        return 0

AREA_INTELLIGENCE = {
    "Kuala Lumpur": {"vacancy":8,"oversupply":5,"hist":3.2,"proj5":32,"conf":"Medium","mrt":["Kajang Line"],"lrt":["Kelana Jaya Line","Ampang Line"],"up":["MRT Circle Line (2028)"]},
    "Mont Kiara": {"vacancy":10,"oversupply":6,"hist":2.8,"proj5":27,"conf":"Medium-High","mrt":[],"lrt":[],"up":["MRT Circle Line (2028)"]},
    "Bangsar": {"vacancy":6,"oversupply":3,"hist":3.0,"proj5":25,"conf":"High","mrt":[],"lrt":["Kelana Jaya Line"],"up":[]},
    "KL Sentral": {"vacancy":9,"oversupply":5,"hist":2.5,"proj5":23,"conf":"Medium","mrt":["Kajang Line"],"lrt":["Kelana Jaya Line","Ampang Line"],"up":["MRT Circle Line (2028)"]},
    "Bukit Jalil": {"vacancy":7,"oversupply":5,"hist":3.5,"proj5":28,"conf":"Medium-High","mrt":[],"lrt":["Sri Petaling Line","Ampang Line"],"up":[]},
    "Petaling Jaya": {"vacancy":6,"oversupply":3,"hist":3.4,"proj5":26,"conf":"High","mrt":["Kajang Line"],"lrt":["Kelana Jaya Line"],"up":[]},
    "Subang Jaya": {"vacancy":8,"oversupply":5,"hist":3.2,"proj5":27,"conf":"Medium","mrt":["Kajang Line"],"lrt":["Kelana Jaya Line"],"up":[]},
    "Puchong": {"vacancy":10,"oversupply":8,"hist":2.8,"proj5":22,"conf":"Medium","mrt":[],"lrt":["Kelana Jaya Line"],"up":[]},
    "Shah Alam": {"vacancy":9,"oversupply":5,"hist":2.5,"proj5":19,"conf":"Medium","mrt":[],"lrt":[],"up":["LRT Shah Alam Line (2030)"]},
    "Kajang": {"vacancy":11,"oversupply":7,"hist":2.2,"proj5":17,"conf":"Medium","mrt":["Kajang Line"],"lrt":[],"up":[]},
    "Penang": {"vacancy":6,"oversupply":3,"hist":4.0,"proj5":32,"conf":"Medium-High","mrt":[],"lrt":[],"up":["Penang LRT"]},
    "Gurney": {"vacancy":4,"oversupply":2,"hist":4.5,"proj5":38,"conf":"Medium-High","mrt":[],"lrt":[],"up":["Penang LRT"]},
    "Bayan Lepas": {"vacancy":7,"oversupply":4,"hist":3.8,"proj5":34,"conf":"High","mrt":[],"lrt":[],"up":["Penang LRT"]},
    "Johor Bahru": {"vacancy":15,"oversupply":9,"hist":1.5,"proj5":22,"conf":"Low-Medium","mrt":[],"lrt":[],"up":["RTS Link (2026)"]},
    "Iskandar Puteri": {"vacancy":20,"oversupply":10,"hist":1.0,"proj5":14,"conf":"Low","mrt":[],"lrt":[],"up":["RTS Link"]},
}

def analyze_and_save(raw_properties, output_file='data/properties.json'):
    from collections import defaultdict
    area_rents = defaultdict(list)
    for p in raw_properties:
        if p.get('rent', 0) > 0 and p.get('size', 0) > 0:
            area_rents[p['area']].append(p['rent'] / p['size'])
    area_avg = {k: sum(v)/len(v) for k, v in area_rents.items()}
    log.info(f"Area rent averages: { {k: round(v,2) for k,v in area_avg.items()} }")
    analyzed = []
    for p in raw_properties:
        if p.get('rent', 0) == 0 and p.get('area') in area_avg:
            p['rent'] = round(area_avg[p['area']] * p.get('size', 900))
        price = p.get('price', 0)
        rent = p.get('rent', 0)
        size = p.get('size', 900)
        area = p.get('area', '')
        if price <= 0 or rent <= 0 or size <= 0:
            continue
        yield_pct = (rent * 12 / price) * 100
        ai = AREA_INTELLIGENCE.get(area, AREA_INTELLIGENCE.get(p.get('state',''), {"vacancy":10,"oversupply":5,"hist":2.5,"proj5":20,"conf":"Medium","mrt":[],"lrt":[],"up":[]}))
        yield_score = min(100, (yield_pct / 7) * 100)
        afford_score = max(0, min(100, 100 - ((price - 200000) / 20000)))
        growth_score = min(100, (ai['hist'] / 5) * 100)
        risk_score = max(0, 100 - (ai['oversupply'] * 10))
        infra_score = min(100, (len(ai['mrt'])*25 + len(ai['lrt'])*18 + len(ai['up'])*12))
        score = round(yield_score*0.30 + afford_score*0.20 + growth_score*0.25 + risk_score*0.15 + infra_score*0.10)
        risk_level = round(100 - risk_score)
        risk_label = 'Low' if risk_level < 30 else 'Medium' if risk_level < 55 else 'High' if risk_level < 75 else 'Very High'
        analyzed.append({'name': p['name'], 'type': p['type'], 'beds': p['beds'], 'size': p['size'], 'price': p['price'], 'rent': p['rent'], 'year_built': p.get('year_built', 0), 'area': p['area'], 'state': p['state'], 'source': p.get('source', ''), 'yield': round(yield_pct, 2), 'price_sqft': round(price/size, 0), 'score': score, 'risk_level': risk_level, 'risk_label': risk_label, 'scraped_at': datetime.now().isoformat()})
    os.makedirs('data', exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(analyzed, f, indent=2)
    log.info(f"Saved {len(analyzed)} analyzed properties to {output_file}")
    log_data = {'last_scan': datetime.now().isoformat(), 'total_scraped': len(raw_properties), 'total_analyzed': len(analyzed), 'areas_scanned': list(set(p['area'] for p in raw_properties))}
    with open('data/scan_status.json', 'w') as f:
        json.dump(log_data, f, indent=2)
    return analyzed

def send_telegram(message):
    token = os.environ.get('TG_TOKEN', '')
    chat_id = os.environ.get('TG_CHAT', '')
    if not token or not chat_id:
        return
    try:
        http_requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}, timeout=10)
    except Exception as e:
        log.error(f"Telegram error: {e}")

def alert_opportunities(analyzed):
    top = [p for p in analyzed if p['score'] >= 75]
    if not top:
        return
    for p in top[:3]:
        msg = f"<b>OPPORTUNITY</b>\n<b>{p['name']}</b>\n{p['area']}, {p['state']}\nRM{p['price']:,.0f} · Rent RM{p['rent']:,.0f}/mo\nYield: <b>{p['yield']}%</b> · Score: {p['score']}/100"
        send_telegram(msg)

if __name__ == '__main__':
    import config
    scraper = Scraper()
    raw = scraper.scrape_all()
    if raw:
        analyzed = analyze_and_save(raw)
        alert_opportunities(analyzed)
        log.info(f"DONE. {len(analyzed)} properties ready.")
    else:
        log.warning("No properties scraped.")
        os.makedirs('data', exist_ok=True)
        with open('data/properties.json', 'w') as f:
            json.dump([], f)
        with open('data/scan_status.json', 'w') as f:
            json.dump({'last_scan': datetime.now().isoformat(), 'total_scraped': 0, 'total_analyzed': 0, 'areas_scanned': [], 'error': 'No data scraped'}, f)
