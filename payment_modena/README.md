# Payment Provider: Modena

Odoo 20 payment provider for [Modena](https://modena.ee). It covers Modena's financing products and Modena Direct bank payments, so one provider gives the customer hire-purchase, Pay in 3 and bank links.

The module depends only on `payment` and `product`. It works wherever Odoo shows a payment form:

- e-shop checkout (`website_sale`),
- sale order and invoice portal, and payment links sent from the back office (no website needed),
- point of sale, through `pos_modena`.

## Payment methods

Each Modena product is its own Odoo payment method, so the customer picks it by name. All of them start inactive; switch on the ones in your Modena contract.

| Odoo payment method | Modena product | Notes |
|---|---|---|
| Pay in 3 | Slice | |
| Hire-purchase | Credit | The customer picks the term on Modena's page |
| Try at home | Click & Try | Pay after trying the goods |
| Business leasing | Business Leasing | Modena finds the company from the person's ID code |
| Business factoring | Business Factoring | Same as above |
| Operating lease | Operating Lease | Needs a Modena asset catalog ID on every product |
| One method per bank | Direct | Created by *Update bank list*, with the bank's logo |

Financing needs the customer's email and phone. When a customer has neither, the financing methods are hidden and only the banks are shown. A customer without a country (anonymous POS payer) sees the banks of the company's country.

## Setup

1. In the Modena portal (Modena Konto > Arendajale > API võtmed) copy the Client ID, Client Secret and Signature Key. Sandbox and live have separate keys.
2. In Odoo open *Accounting > Configuration > Payment Providers > Modena* and enter the keys.
3. Leave *Live* off to use the Modena sandbox (`api-dev.modena.ee`). Turn it on for production (`api.modena.ee`).
4. Publish the provider and activate the payment methods you sell with.
5. Press *Update bank list* to create the Direct bank methods. A daily cron keeps the list current; new banks are created inactive.
6. Optional, per payment method: term in months, minimum and maximum amount.

### Requirements

- Odoo must be reachable on a public HTTPS address. Modena sends the customer back and posts notifications to it.
- `web.base.url` must be that address. Behind a reverse proxy, set `proxy_mode = True` and make sure the proxy sends `X-Forwarded-Host` and `X-Forwarded-Proto`; Odoo 20 ignores `proxy_mode` without `X-Forwarded-Host`, and the return links then come out as `http://`.

## How a payment runs

1. Odoo sends the order lines, totals and customer to Modena and gets an application ID back (HTTP 302).
2. The customer is redirected to Modena (financing) or to their bank (Direct).
3. Modena returns the customer to `/payment/modena/return` or `/payment/modena/cancel` and posts a notification to `/payment/modena/webhook`.
4. Odoo does not take the payment state from these requests. It checks that the application ID belongs to the transaction, verifies the HMAC signature when Modena sends one (Direct), and then asks Modena's status API.

| Modena status | Odoo transaction |
|---|---|
| OUTSTANDING, IN_MANUAL_REVIEW | pending |
| SUCCESS | done |
| REJECTED, EXPIRED | cancelled |
| FAILED | error |

A cron runs every 30 minutes and asks Modena about pending transactions, because Modena only notifies successful financing applications.

If the customer leaves the Modena page, the transaction is cancelled so the cart is free again. When Modena approves that application later anyway, the transaction is set to done and the sale order or invoice gets a note and an activity to check for a double payment.

## Operating lease

Fill *Modena Asset Catalog ID* and *Modena Buyback %* on the product (Sales tab). The method shows only when every line of the sale order has a catalog ID. The term (12, 24 or 36 months) is set on the payment method.

## Limitations

- Refunds and cancellations are done in the Modena portal; Modena has no API for them.
- EUR only.
- Card payments appear only if Modena includes `CARD` in the bank list of your account. The sandbox does not.

## Tests

```bash
odoo -d <db> -u payment_modena --test-tags /payment_modena --stop-after-init
```

The tests mock all Modena calls. The sale order tests are skipped when `sale` is not installed.
