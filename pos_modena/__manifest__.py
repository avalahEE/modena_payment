{
    "name": "POS Modena",
    "version": "20.0.1.0.0",
    "category": "Sales/Point of Sale",
    "summary": "Pay POS orders with Modena from the customer's phone: QR code or printed payment slip.",
    "author": "Avalah",
    "website": "https://www.avalah.ee",
    "depends": ["pos_online_payment", "pos_stock", "payment_modena"],
    "data": [
        "views/pos_payment_method_views.xml",
        "views/templates.xml",
        "receipt/payment_slip.xml",
        "data/ir_cron_data.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_modena/static/src/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "license": "LGPL-3",
}
