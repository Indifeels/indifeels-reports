"""GA4 website sessions by source/campaign; kept separate from Shopify totals."""
from collections import defaultdict
from datetime import date, timedelta
from html import escape
from urllib.parse import parse_qs, urlsplit

METRICS = ['sessions', 'add_to_carts', 'checkouts', 'ecommerce_purchases', 'purchase_revenue']
FIELDS = ['date', 'landing_page_plus_query_string', 'session_source_medium',
          'session_manual_source', 'session_manual_medium', 'session_manual_campaign_name',
          'session_manual_ad_content'] + METRICS
CHANNELS = ['Instagram – Organic', 'FB Page – Organic', 'FB Page – Third-Party Postings',
            'FB Marketplace', 'Facebook – Paid Campaigns', 'Instagram – Paid Campaigns',
            'Meta – Paid Campaigns (platform unspecified)', 'Google Ads – Paid Campaigns',
            'GMB – Organic', 'Organic Search', 'WhatsApp', 'Email', 'SMS',
            'Store QR / Flyers', 'Direct / Unknown', 'Other Referrals']


def classify(row):
    q = parse_qs(urlsplit(str(row.get('landing_page_plus_query_string') or '')).query)
    code = q.get('source', [''])[0].lower()
    page = q.get('page', [''])[0]
    sm = str(row.get('session_source_medium') or '').lower()
    source = str(row.get('session_manual_source') or '').lower()
    medium = str(row.get('session_manual_medium') or '').lower()
    campaign = str(row.get('session_manual_campaign_name') or '')
    content = str(row.get('session_manual_ad_content') or '')
    paid = (medium in ['paid', 'paid_social', 'cpc', 'ppc', 'cpm', 'display'] or
            any(sm.endswith(' / '+m) for m in ['paid', 'paid_social', 'cpc', 'ppc', 'cpm', 'display']) or
            medium.startswith('tracked') or medium.startswith('non tracked'))
    if paid or q.get('gclid') or q.get('gbraid') or q.get('wbraid'):
        if 'google' in source or 'google' in sm or q.get('gclid') or q.get('gbraid') or q.get('wbraid'):
            channel = 'Google Ads – Paid Campaigns'
        elif source in ['ig', 'instagram'] or sm.startswith('instagram /') or sm.startswith('ig /'):
            channel = 'Instagram – Paid Campaigns'
        elif source in ['fb', 'facebook'] or sm.startswith('facebook /') or sm.startswith('fb /'):
            channel = 'Facebook – Paid Campaigns'
        elif 'facebook' in source or 'instagram' in source:
            channel = 'Meta – Paid Campaigns (platform unspecified)'
        else:
            channel = 'Other Referrals'
        return channel, campaign or '(campaign unavailable)'
    if code == 'ig': return 'Instagram – Organic', 'source=ig'
    if code == 'fb' and page: return 'FB Page – Third-Party Postings', page
    if code == 'fb': return 'FB Page – Organic', 'source=fb'
    if code == 'fm' or campaign == 'fb_marketplace': return 'FB Marketplace', content or 'source=fm'
    if code == 'gm' or source == 'gmb' or campaign.lower().startswith('gmb_'): return 'GMB – Organic', campaign or 'source=gm'
    if campaign == 'fb_third_party': return 'FB Page – Third-Party Postings', content or '(page code missing)'
    if campaign == 'fb_page_organic': return 'FB Page – Organic', content or campaign
    if source in ['instagram', 'ig']: return 'Instagram – Organic', content or campaign
    if medium == 'organic' or sm.endswith(' / organic'): return 'Organic Search', source or sm
    if source == 'whatsapp' or code == 'wa': return 'WhatsApp', campaign or code
    if medium == 'email' or code == 'em': return 'Email', campaign or code
    if medium == 'sms' or code == 'sms': return 'SMS', campaign or code
    if code in ['qr', 'flyer']: return 'Store QR / Flyers', code
    if 'instagram.com' in sm: return 'Instagram – Organic', 'Untagged referral'
    if 'facebook.com' in sm: return 'Other Referrals', 'Facebook – placement unknown'
    if sm.startswith('(direct)') or not sm or sm.startswith('(data not available)') or sm.startswith('(not set)'):
        return 'Direct / Unknown', 'Source unavailable'
    return 'Other Referrals', sm

ACCOUNT = '326170578'

def section(src):
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.fromisoformat(src['now']).astimezone(ZoneInfo('Australia/Melbourne'))
    rows = []
    for row in src.get('website_links') or []:
        ds = str(row['date'])[:10]
        d = date.fromisoformat(ds) if '-' in ds else date.fromisoformat(ds[:4]+'-'+ds[4:6]+'-'+ds[6:8])
        channel, detail = classify(row)
        rows.append(dict(date=d.isoformat(), channel=channel, detail=detail,
                         values=[float(row.get(field) or 0) for field in METRICS]))
    payload = dict(today=now.date().isoformat(), completed=src.get('completed_end',src['end']),
                   updated=now.isoformat(), ok=src.get('fetch_status',{}).get('website_links',{}).get('ok',False),
                   channels=CHANNELS, rows=rows)
    encoded = json.dumps(payload,ensure_ascii=True).replace('<','\\u003c')
    return '<section id="website-link-tracking"><h2>Website Traffic</h2><div class="wt-data" hidden>'+escape(encoded)+'</div><div class="wt-view"></div></section>'
