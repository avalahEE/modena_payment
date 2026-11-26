# Modena for Odoo 20

| Module | What it does |
|---|---|
| [payment_modena](payment_modena/README.md) | Modena payment provider: financing products and bank payments for the e-shop, portal and payment links |
| [pos_modena](pos_modena/README.md) | Modena at the till: QR code, printed payment slip, stock reservation while the customer pays |

## Tests

```bash
odoo -d <db> -u payment_modena,pos_modena --test-tags /payment_modena,/pos_modena --stop-after-init
```
