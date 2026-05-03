"""இந்தியா/மலேசியா — தமிழ் மொழிபெயர்ப்புகள் (Tamil translations)

面向马来西亚 Tamil 市场，支持 Tamil 界面显示。
翻译按模块组织：CATEGORIES（菜品分类）、UI（界面文本）、RECEIPT（小票打印）
使用马来西亚 Tamil 方言特色，技术术语保留英文音译。
"""

LANG_CODE = "ta_IN"
LANG_NAME = "தமிழ்"

CATEGORIES = {
    "seafood": "கடல் உணவு",
    "meat": "இறைச்சி",
    "vegetable": "காய்கறிகள்",
    "soup": "சூப்",
    "rice_noodle": "சாதம் & நூடுல்ஸ்",
    "dessert": "இனிப்பு",
    "beverage": "பானங்கள்",
    "appetizer": "சிற்றுண்டி",
    "signature": "சிறப்பு",
    "new_arrival": "புதியது",
    "promotion": "விளம்பரம்",
    "set_menu": "செட் மெனு",
}

UI = {
    # 通用
    "confirm": "உறுதிப்படுத்து",
    "cancel": "ரத்து",
    "save": "சேமி",
    "delete": "நீக்கு",
    "edit": "திருத்து",
    "back": "பின்",
    "next": "அடுத்து",
    "submit": "சமர்ப்பி",
    "search": "தேடு",
    "loading": "ஏற்றுகிறது...",
    "success": "வெற்றி",
    "fail": "தோல்வி",
    "retry": "மீண்டும் முயற்சி",

    # 收银
    "checkout": "செக்அவுட்",
    "total": "மொத்தம்",
    "subtotal": "துணை மொத்தம்",
    "discount": "தள்ளுபடி",
    "payable": "செலுத்த வேண்டியது",
    "change": "மீதி",
    "cash": "ரொக்கம்",
    "settle": "தீர்க்க",
    "print_receipt": "ரசீது அச்சிடுக",
    "open_cashbox": "பணப்பெட்டி திற",

    # SST
    "sst_included": "SST உள்ளடக்கியது",
    "sst_exempt": "SST விலக்கு",
    "sst_standard": "நிலையான விகிதம் (6%)",
    "sst_specific": "குறிப்பிட்ட விகிதம் (8%)",

    # e-Invoice
    "einvoice": "மின்-விலைப்பட்டி",
    "einvoice_request": "விலைப்பட்டி கோருக",
    "einvoice_personal": "தனிநபர்",
    "einvoice_company": "நிறுவனம்",
    "einvoice_tax_no": "வரி எண்",
    "einvoice_issued": "வழங்கப்பட்டது",
    "einvoice_failed": "தோல்வி",
    "einvoice_cancel": "விலைப்பட்டி ரத்து",

    # 桌台
    "table_empty": "காலி",
    "table_occupied": "நிரம்பியது",
    "table_reserved": "முன்பதிவு",
    "guest_count": "{count} விருந்தினர்கள்",
}

DISH_NAMES = {}

RECEIPT = {
    "header": "ரசீது",
    "order_no": "ஆர்டர் எண்",
    "table_no": "மேஜை",
    "items": "பொருட்கள்",
    "qty": "அளவு",
    "price": "விலை",
    "total": "மொத்தம்",
    "subtotal": "துணை மொத்தம்",
    "sst": "SST (6%)",
    "sst_8": "SST (8%)",
    "sst_exempt": "SST விலக்கு",
    "discount": "தள்ளுபடி",
    "payable": "செலுத்த வேண்டியது",
    "cash": "ரொக்கம் (RM)",
    "change": "மீதி",
    "payment_method": "செலுத்தும் முறை",
    "thank_you": "நன்றி! சுவையாக உண்ணுங்கள்!",
    "qr_scan": "அடுத்த ஆர்டருக்கு QR குறியீட்டை ஸ்கேன் செய்யவும்",
    "date": "தேதி",
    "time": "நேரம்",
    "cashier": "காசாளர்",
}
