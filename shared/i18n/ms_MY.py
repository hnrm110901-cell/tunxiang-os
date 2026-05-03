"""马来西亚 — 马来语（Bahasa Malaysia）翻译

面向马来西亚市场，支持马来语界面显示。
翻译按模块组织：CATEGORIES（菜品分类）、UI（界面文本）、RECEIPT（小票打印）
"""

LANG_CODE = "ms_MY"
LANG_NAME = "Bahasa Malaysia"

CATEGORIES = {
    "seafood": "Makanan Laut",
    "meat": "Daging",
    "vegetable": "Sayur-sayuran",
    "soup": "Sup",
    "rice_noodle": "Nasi & Mee",
    "dessert": "Pencuci Mulut",
    "beverage": "Minuman",
    "appetizer": "Pembuka Selera",
    "signature": "Signature",
    "new_arrival": "Baharu",
    "promotion": "Promosi",
    "set_menu": "Set Makanan",
}

UI = {
    # 通用
    "confirm": "Sahkan",
    "cancel": "Batal",
    "save": "Simpan",
    "delete": "Padam",
    "edit": "Sunting",
    "back": "Kembali",
    "next": "Seterusnya",
    "submit": "Hantar",
    "search": "Cari",
    "loading": "Memuatkan...",
    "success": "Berjaya",
    "fail": "Gagal",
    "retry": "Cuba Semula",

    # 收银
    "checkout": "Pembayaran",
    "total": "Jumlah",
    "subtotal": "Subjumlah",
    "discount": "Diskaun",
    "payable": "Perlu Dibayar",
    "change": "Wang Kembali",
    "cash": "Tunai",
    "settle": "Selesai",
    "print_receipt": "Cetak Resit",
    "open_cashbox": "Buka Laci Wang",

    # SST
    "sst_included": "Termasuk SST",
    "sst_exempt": "Dikecualikan SST",
    "sst_standard": "Kadar Standard (6%)",
    "sst_specific": "Kadar Khusus (8%)",

    # e-Invoice
    "einvoice": "e-Invois",
    "einvoice_request": "Minta Invois",
    "einvoice_personal": "Individu",
    "einvoice_company": "Syarikat",
    "einvoice_tax_no": "No. Cukai",
    "einvoice_issued": "Dikeluarkan",
    "einvoice_failed": "Gagal",
    "einvoice_cancel": "Batal Invois",

    # 桌台
    "table_empty": "Kosong",
    "table_occupied": "Diduduki",
    "table_reserved": "Ditempah",
    "guest_count": "{count} Tetamu",
}

DISH_NAMES = {}

RECEIPT = {
    "header": "RESIT",
    "order_no": "No. Pesanan",
    "table_no": "Meja",
    "items": "Item",
    "qty": "Kuantiti",
    "price": "Harga",
    "total": "Jumlah",
    "subtotal": "Subjumlah",
    "sst": "SST (6%)",
    "sst_8": "SST (8%)",
    "sst_exempt": "Dikecualikan SST",
    "discount": "Diskaun",
    "payable": "Perlu Dibayar",
    "cash": "Tunai (RM)",
    "change": "Wang Kembali",
    "payment_method": "Cara Bayaran",
    "thank_you": "Terima Kasih. Selamat Makan!",
    "qr_scan": "Imbas Kod QR untuk tempahan seterusnya",
    "date": "Tarikh",
    "time": "Masa",
    "cashier": "Juruwang",
}
