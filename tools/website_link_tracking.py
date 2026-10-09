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
    end = date.fromisoformat(src.get('completed_end', src['end'])[:10])
    out = ['<section class="panel" id="website-link-tracking"><h2>Website Link Tracking</h2>',
           '<p class="hint">GA4 via Windsor · Visits are website sessions, not raw link clicks. Purchases and revenue use GA4 session attribution and are separate from the Shopify totals above. All periods exclude today. Recent GA4 data can arrive late.</p>']
    status = src.get('fetch_status', {}).get('website_links', {})
    if not status.get('ok'):
        out.append('<p class="flag bad">Website tracking data unavailable for this refresh. No zero totals have been substituted.</p>')
    else:
        for label, days in [('Yesterday', 1), ('Last 7 days', 7), ('Last 30 days', 30)]:
            start = end - timedelta(days=days-1)
            agg = defaultdict(lambda: [0.0]*5)
            breakdown = defaultdict(lambda: defaultdict(lambda: [0.0]*5))
            for row in src.get('website_links', []):
                ds = str(row['date'])[:10]
                d = date.fromisoformat(ds) if '-' in ds else date.fromisoformat(ds[:4]+'-'+ds[4:6]+'-'+ds[6:8])
                if not start <= d <= end:
                    continue
                channel, detail = classify(row)
                for i, field in enumerate(METRICS):
                    value = float(row.get(field) or 0)
                    agg[channel][i] += value
                    breakdown[channel][detail][i] += value
            out.append('<details'+(' open' if days == 1 else '')+'><summary style="cursor:pointer;padding:12px 0;font-weight:600">'+label+' · '+start.isoformat()+' to '+end.isoformat()+'</summary><div class="scroll"><table><thead><tr><th>Source / campaign</th><th>Visits</th><th>Add to carts</th><th>Checkouts</th><th>Purchases</th><th>Revenue*</th></tr></thead><tbody>')
            def cells(values):
                return ''.join('<td>'+format(v, ',.0f')+'</td>' for v in values[:4])+'<td>'+format(values[4], ',.2f')+'</td>'
            for channel in CHANNELS:
                values = agg.get(channel, [0.0]*5)
                out.append('<tr><td><strong>'+escape(channel)+'</strong></td>'+cells(values)+'</tr>')
                for detail, detail_values in sorted(breakdown[channel].items(), key=lambda item: -item[1][0]):
                    if detail_values[0] or detail_values[3]:
                        out.append('<tr><td style="padding-left:25px;color:var(--muted)">'+escape(detail)+'</td>'+cells(detail_values)+'</tr>')
            if not agg:
                out.append('<tr><td colspan="6">No source-attributed sessions reported for this period.</td></tr>')
            out.append('</tbody></table></div></details>')
    out.append('<p class="hint">*Revenue is in the GA4 property currency. Short codes classify the session landing link; paid signals take priority. Untagged Facebook referrals cannot identify your own page, Marketplace or a third-party page. Combined Meta campaigns stay platform unspecified. Sharing the same code across placements combines their results.</p><details><summary style="cursor:pointer;padding:12px 0;font-weight:600">Your short tracking links</summary>')
    for label, suffix in [('Instagram – Organic','?source=ig'), ('FB Page – Organic','?source=fb'), ('FB Marketplace','?source=fm'), ('GMB – Organic','?source=gm'), ('FB Page – Third-Party Postings','?source=fb&page=PAGECODE')]:
        url = 'https://indifeels.com/'+suffix
        out.append('<p><strong>'+label+'</strong><br><input aria-label="'+label+' tracking URL" readonly onclick="this.select()" style="box-sizing:border-box;width:100%;padding:10px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px" value="'+escape(url, quote=True)+'"></p>')
    out.append('<p class="hint">Replace PAGECODE with your existing page code. Use each link only for its named placement. Paid ads keep their existing campaign tags.</p></details></section>')
    return ''.join(out)
