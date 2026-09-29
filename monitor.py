"""Joybuy NL public campaign monitor. Python 3.12+, standard library only."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class PageText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


def allowed(url):
    p = urlsplit(url)
    return p.scheme == 'https' and p.hostname in ('www.joybuy.nl', 'm.joybuy.nl') and not p.username and not p.password


def fetch(url):
    if not allowed(url):
        raise ValueError('Only Joybuy NL HTTPS pages are allowed')
    req = Request(url, headers={'User-Agent': 'JoybuyDealMonitor/0.1', 'Accept-Language': 'nl-NL,nl;q=0.9'})
    with urlopen(req, timeout=35) as response:
        if not allowed(response.url) or 'error403' in response.url:
            raise ValueError('Page blocked or redirected away from Joybuy NL')
        data = response.read(12_000_001)
        if len(data) > 12_000_000:
            raise ValueError('Page too large')
        return data.decode('utf-8')


def parse_page(html, url):
    if re.search(r'<title>[^<]*(?:403|forbidden)', html, re.I):
        raise ValueError('Access blocked')
    match = re.search(r'window\.__react_data__\s*=\s*', html)
    data = json.JSONDecoder().raw_decode(html[match.end():])[0] if match else {}
    products = {}
    recognized = 0
    for obj in walk(data):
        ext = obj.get('productExtInfo')
        if not isinstance(ext, dict):
            continue
        recognized += 1
        common = ext.get('itemCommonView', {})
        if common.get('isAvailable') is False or common.get('inStock') is False:
            continue
        if ext.get('localInfo', {}).get('currency', 'EUR') != 'EUR':
            continue
        price = ext.get('itemPriceView', {}).get('priceInfo', {})
        try:
            current, reference = float(price['mainPrice']), float(price['crossOffPrice'])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 < current < reference:
            continue
        sku = str(obj.get('skuId', ''))
        name = ext.get('itemTitleView', {}).get('title')
        if not sku or not name:
            continue
        products[sku] = {'id': 'sku:' + sku, 'kind': 'product', 'name': name,
                         'price': current, 'reference': reference,
                         'basis': price.get('crossOffPriceText') or '网站划线价，非历史成交价',
                         'discount': (1 - current / reference) * 100, 'url': url}
    text = PageText()
    text.feed(html)
    visible = re.sub(r'\s+', ' ', ' '.join(text.parts))
    coupon_patterns = [
        r'€\s*\d+(?:[.,]\d+)?\s*[-–]\s*€\s*\d+(?:[.,]\d+)?',
        r'(?:Geldig bij bestellingen vanaf|Te gebruiken bij besteding vanaf)\s*€\s*\d+(?:[.,]\d+)?\s*€\s*\d+(?:[.,]\d+)?\s*korting',
        r'(?:Voer de code in bij het afrekenen|korting met code)\s*:\s*\[?[A-Z0-9_-]+\]?',
    ]
    coupons = []
    for pattern in coupon_patterns:
        for match in re.finditer(pattern, visible, re.I):
            evidence = match.group(0)
            identity = hashlib.sha256((url + '|' + evidence).encode()).hexdigest()[:24]
            coupons.append({'id': 'coupon:' + identity, 'kind': 'coupon',
                            'name': evidence, 'url': url})
    links = []
    for match in re.finditer(r'(?:https://(?:www|m)\.joybuy\.nl)?/campaign/active/[A-Za-z0-9]+', html.replace('\\/', '/')):
        link = urljoin(url, match.group(0))
        if allowed(link) and link not in links:
            links.append(link)
    # Empty JS shells and layout changes must not count as successful scans.
    if not recognized and not coupons:
        raise ValueError('No recognizable product or coupon data; page may require JavaScript')
    return list(products.values()) + coupons, links, recognized


def new_deals(deals, seen, threshold):
    result = []
    for deal in deals:
        old = seen.get(deal['id'])
        if deal['kind'] == 'coupon':
            if old is None:
                result.append(deal)
        elif deal['discount'] >= threshold and (old is None or deal['price'] < old['price'] - 0.005):
            result.append(deal)
    return sorted(result, key=lambda d: (d['kind'] != 'coupon', -d.get('discount', 0)))


def render(deals, errors, checked):
    lines = [f'检查时间：{datetime.now(ZoneInfo("Europe/Amsterdam")).isoformat(timespec="minutes")}',
             f'成功读取 {checked} 个页面。仅覆盖这些公开页面，不代表全站。',
             '价格不含运费；优惠、配送地区及库存以结账为准。未自动叠加优惠券。']
    for d in deals:
        if d['kind'] == 'product':
            lines += [f'### {d["name"]}', f'€{d["price"]:.2f} ｜相对参考价优惠 {d["discount"]:.1f}%',
                      f'参考价 €{d["reference"]:.2f}（{d["basis"]}，非历史最低价比较）',
                      f'商品编号：{d["id"][4:]}']
        else:
            lines += [f'### 满减/优惠码线索：{d["name"]}', '有效期、适用商品及新客/会员限制：需在活动页核实；旧活动页可能仍可访问。']
        lines += [f'[查看来源活动页]({d["url"]})', '']
    if errors:
        lines += ['### 部分页面未能检查', *errors]
    return '\n\n'.join(lines)


def send_email(title, body):
    required = ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD', 'MAIL_FROM', 'MAIL_TO')
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError('Missing SMTP or mail secrets; see README')
    message = EmailMessage()
    message['Subject'] = title
    message['From'] = os.environ['MAIL_FROM']
    message['To'] = os.environ['MAIL_TO']
    message.set_content(body)
    host = os.environ['SMTP_HOST']
    port = int(os.environ.get('SMTP_PORT') or '465')
    context = ssl.create_default_context()
    try:
        if port == 465:
            client = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        elif port == 587:
            client = smtplib.SMTP(host, port, timeout=30)
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        else:
            raise RuntimeError('Use encrypted SMTP on port 465 or 587')
        with client:
            client.login(os.environ['SMTP_USER'], os.environ['SMTP_PASSWORD'])
            refused = client.send_message(message)
            if refused:
                raise RuntimeError('Recipient rejected')
    except Exception:
        raise RuntimeError('Email delivery failed or is unknown; check SMTP settings and sent-mail/provider logs') from None


def send(title, body, channel='wechat'):
    if channel == 'email':
        return send_email(title, body)
    if channel != 'wechat':
        raise RuntimeError('notification_channel must be wechat or email')
    key = os.environ.get('SERVERCHAN_SENDKEY', '')
    if not re.fullmatch(r'SCT[A-Za-z0-9]+', key):
        raise RuntimeError('Configure a ServerChan Turbo SCT SendKey in the repository secret')
    request = Request('https://sctapi.ftqq.com/' + key + '.send',
                      data=urlencode({'title': title[:100], 'desp': body}).encode(), method='POST')
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except Exception:
        # Do not print request URLs: the SendKey is in the URL.
        raise RuntimeError('Push request failed; delivery is unknown. Check ServerChan console') from None
    if result.get('code') != 0:
        raise RuntimeError('ServerChan rejected the push; check quota and channel settings')


def run():
    args = argparse.ArgumentParser()
    args.add_argument('--dry-run', action='store_true')
    opts = args.parse_args()
    cfg = json.loads(Path('config.json').read_text())
    state_path = Path('state.json')
    state = json.loads(state_path.read_text()) if state_path.exists() else {'seen': {}, 'days': {}}
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    state['days'] = {today: state.get('days', {}).get(today, 0)}
    queue = list(cfg['seed_urls'])
    visited, all_deals, errors, successes = set(), {}, [], 0
    product_records = 0
    while queue and len(visited) < cfg['max_pages']:
        url = queue.pop(0)
        if url in visited or not allowed(url):
            continue
        visited.add(url)
        try:
            html = fetch(url)
            # Discover links even if this page itself contains no supported cards.
            for link in re.findall(r'https://www\.joybuy\.nl/campaign/active/[A-Za-z0-9]+', html.replace('\\/', '/')):
                if link not in visited and link not in queue:
                    queue.append(link)
            deals, links, count = parse_page(html, url)
            for deal in deals:
                prior = all_deals.get(deal['id'])
                if prior is None or deal.get('price', 0) < prior.get('price', 0):
                    all_deals[deal['id']] = deal
            queue.extend(link for link in links if link not in visited and link not in queue)
            successes += 1
            product_records += count
        except Exception as exc:
            errors.append(f'{url} — {type(exc).__name__}')
        if queue:
            time.sleep(2)
    pending = new_deals(list(all_deals.values()), state['seen'], cfg['min_discount_percent'])
    selected = pending[:cfg['max_deals_per_message']]
    body = render(selected, errors, successes)
    Path('report.md').write_text(body)
    print(f'Pages: {successes}/{len(visited)}; product records: {product_records}; new deals: {len(pending)}; failures: {len(errors)}')
    if opts.dry_run:
        print('DRY RUN: no push sent, no state changed. See report.md.')
        return 1 if errors else 0
    channel = cfg.get('notification_channel', 'wechat')
    if channel == 'wechat' and not os.environ.get('SERVERCHAN_SENDKEY'):
        raise RuntimeError('Missing SERVERCHAN_SENDKEY; nothing sent')
    # Reserve the fifth free daily message for other use; persistent state prevents hourly repeats.
    should_alert_error = errors and state.get('error_day') != today
    if (selected or should_alert_error) and state['days'][today] < cfg['max_pushes_per_day']:
        title = f'Joybuy：{len(selected)} 条优惠线索' if selected else 'Joybuy：部分页面检查失败'
        send(title, body, channel)
        for deal in selected:
            state['seen'][deal['id']] = {'price': deal.get('price'), 'sent_at': today}
        state['days'][today] += 1
        if errors:
            state['error_day'] = today
    # Do not mark unsent deals as seen; they are reconsidered on the next fresh scan.
    temp = state_path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    temp.replace(state_path)
    return 1 if errors else 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except Exception as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
