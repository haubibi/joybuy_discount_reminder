import json
import unittest
from unittest.mock import patch
from monitor import parse_page, new_deals, send_email

URL = 'https://www.joybuy.nl/campaign/active/test'


class MonitorTests(unittest.TestCase):
    def test_prices_stock_and_coupons(self):
        product = {'skuId': '123', 'productExtInfo': {
            'itemTitleView': {'title': 'Test product'},
            'itemPriceView': {'priceInfo': {'mainPrice': '20.00', 'crossOffPrice': '50.00', 'crossOffPriceText': 'Adviesprijs:'}},
            'itemCommonView': {'inStock': True, 'isAvailable': True}}}
        page = '<p>Geldig bij bestellingen vanaf €49</p><p>€5 korting</p><script>window.__react_data__ = ' + json.dumps([product]) + ';</script>'
        deals, _, count = parse_page(page, URL)
        self.assertEqual(count, 1)
        self.assertEqual(len(deals), 2)
        self.assertEqual(deals[0]['discount'], 60)
        self.assertEqual(len(new_deals(deals, {'sku:123': {'price': 20}}, 50)), 1)
        self.assertEqual(len(new_deals(deals, {'sku:123': {'price': 25}}, 50)), 2)
        product['productExtInfo']['itemCommonView']['inStock'] = False
        page = '<script>window.__react_data__ = ' + json.dumps([product]) + ';</script>'
        self.assertEqual(parse_page(page, URL)[0], [])

    def test_blocked_and_shell_are_not_zero_deals(self):
        for html in ['<title>403 Forbidden</title>', '<div id="app"></div>']:
            with self.assertRaises(ValueError):
                parse_page(html, URL)

    def test_scripts_do_not_create_fake_coupons(self):
        with self.assertRaises(ValueError):
            parse_page('<script>const fake="€49-€10";</script>', URL)

    def test_mail_unicode_and_secret_safe_failure(self):
        env = {'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': '465',
               'SMTP_USER': 'me@example.com', 'SMTP_PASSWORD': 'private-value',
               'MAIL_FROM': 'me@example.com', 'MAIL_TO': 'me@example.com'}
        with patch.dict('os.environ', env), patch('monitor.smtplib.SMTP_SSL') as smtp:
            client = smtp.return_value
            client.send_message.return_value = {}
            send_email('Joybuy 优惠', '现价 €12.50')
            message = client.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'me@example.com')
            self.assertIn('€12.50', message.get_content())
            client.login.side_effect = RuntimeError('private-value')
            with self.assertRaises(RuntimeError) as error:
                send_email('Test', 'Test')
            self.assertNotIn('private-value', str(error.exception))


if __name__ == '__main__':
    unittest.main()
