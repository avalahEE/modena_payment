# POS Modena

Lets a point of sale customer pay with Modena on their own phone: hire-purchase, Pay in 3, Try at home or a bank link. The cashier presses one button and the customer chooses how to pay.

Depends on `pos_online_payment`, `pos_stock` and `payment_modena`. No website or sales app needed.

## At the till

1. The cashier rings up the order, selects the customer and picks the Modena payment method.
2. *Validate* shows a QR code. The customer scans it and sees the shop, the order lines and every Modena option the shop offers.
3. If the customer pays right away, the till finishes the order by itself.
4. If the customer needs time, the cashier presses *Print payment slip*:
   - the receipt printer prints an unpaid slip with the order lines, the amount, a "valid until" time and the customer's own QR code,
   - the order is parked and its products are reserved in stock, so the e-shop cannot sell them meanwhile,
   - the till opens a new order for the next customer.
5. When the payment lands, the till shows *Order 1004 has been paid* with a *Print receipt* button.
6. When Modena rejects the application, the till shows a warning with *Open order*, so the cashier can take another payment.
7. When the slip runs out before the customer has started paying, a cron (every 5 minutes) cancels the order, releases the reserved stock and tells the till. Scanning the old slip then shows that the time to pay has ended.

A customer who started the payment before the slip ran out keeps their order: the application is already with Modena.

Without a selected customer only the bank payments are offered, because Modena needs an email and phone for financing.

## Setup

1. Set up the Modena provider in `payment_modena`.
2. Create a POS payment method of type *Online* and allow the Modena provider on it.
3. On that payment method, *Print payment slip* is on by default. *Slip valid for (minutes)* is 30 by default.
4. Add the payment method to the POS.

## Closing the session

Odoo does not close a session with draft orders, so parked orders have to be paid or cancelled first. Cancelling releases their stock. A Modena approval that arrives after closing is kept as a customer payment; the POS order gets a note and the payment gets an activity, so accounting can finish it by hand.

## Notes

- Tills cache data in the browser and only refetch records whose `write_date` changed. Installing the module touches the existing payment methods for that reason. After changing fields by hand in the database, clear the till's site data.
- Without a receipt printer Odoo falls back to the browser's print dialog.
- For waits longer than a shift, use a quotation with a payment link instead.

## Tests

```bash
odoo -d <db> -u pos_modena --test-tags /pos_modena --stop-after-init
```
