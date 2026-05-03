"""印度尼西亚 — 印尼语（Bahasa Indonesia）翻译

面向印度尼西亚市场，支持印尼语界面显示。
注意：印尼语（Bahasa Indonesia）与马来语（Bahasa Malaysia）在词汇上存在差异。
PPN（Pajak Pertambahan Nilai）是印尼增值税。
"""

LANG_CODE = "id_ID"
LANG_NAME = "Bahasa Indonesia"

CATEGORIES = {
    "seafood": "Makanan Laut",
    "meat": "Daging",
    "vegetable": "Sayur-sayuran",
    "soup": "Sup",
    "rice_noodle": "Nasi & Mie",
    "dessert": "Pencuci Mulut",
    "beverage": "Minuman",
    "appetizer": "Pembuka Selera",
    "signature": "Andalan",
    "new_arrival": "Menu Baru",
    "promotion": "Promosi",
    "set_menu": "Paket Makanan",
}

UI = {
    # 通用
    "confirm": "Konfirmasi",
    "cancel": "Batal",
    "save": "Simpan",
    "delete": "Hapus",
    "edit": "Ubah",
    "back": "Kembali",
    "next": "Lanjut",
    "submit": "Kirim",
    "search": "Cari",
    "loading": "Memuat...",
    "success": "Berhasil",
    "fail": "Gagal",
    "retry": "Coba Lagi",

    # 收银
    "checkout": "Pembayaran",
    "total": "Jumlah",
    "subtotal": "Subtotal",
    "discount": "Diskon",
    "payable": "Terbayar",
    "change": "Kembalian",
    "cash": "Tunai",
    "settle": "Bayar",
    "print_receipt": "Cetak Struk",
    "open_cashbox": "Buka Laci Kas",

    # PPN 11%
    "ppn_included": "Termasuk PPN",
    "ppn_exempt": "Bebas PPN",
    "ppn_standard": "Tarif Standar (11%)",
    "ppn_luxury": "Barang Mewah (12%)",

    # e-Faktur
    "einvoice": "e-Faktur",
    "einvoice_request": "Buat Faktur",
    "einvoice_personal": "Pribadi",
    "einvoice_company": "Perusahaan",
    "einvoice_tax_no": "NPWP",
    "einvoice_issued": "Terbit",
    "einvoice_failed": "Gagal",
    "einvoice_cancel": "Batalkan Faktur",

    # 桌台
    "table_empty": "Kosong",
    "table_occupied": "Terisi",
    "table_reserved": "Dipesan",
    "guest_count": "{count} Tamu",
}

DISH_NAMES = {}

RECEIPT = {
    "header": "STRUK",
    "order_no": "No. Pesanan",
    "table_no": "Meja",
    "items": "Item",
    "qty": "Jumlah",
    "price": "Harga",
    "total": "Total",
    "subtotal": "Subtotal",
    "ppn": "PPN (11%)",
    "ppn_luxury": "PPN (12%)",
    "ppn_exempt": "Bebas PPN",
    "discount": "Diskon",
    "payable": "Terbayar",
    "cash": "Tunai (Rp)",
    "change": "Kembalian",
    "payment_method": "Cara Bayar",
    "thank_you": "Terima Kasih. Selamat Makan!",
    "qr_scan": "Scan Kode QR untuk pesan berikutnya",
    "date": "Tanggal",
    "time": "Waktu",
    "cashier": "Kasir",
}
