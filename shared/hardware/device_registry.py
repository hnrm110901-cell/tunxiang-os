"""屯象OS 硬件设备注册中心

中国连锁餐饮行业主流硬件品牌型号全集。
每个设备包含：品牌/型号/品类/接口/协议/推荐场景/配置参数。

数据来源：基于中国连锁餐饮行业实际部署情况整理，
覆盖北洋、佳博、爱普生、商米、客如云、新大陆、霍尼韦尔等主流品牌。
"""

# ─── 设备品类定义 ───

DEVICE_CATEGORIES = {
    "printer": "热敏打印机",
    "pos_terminal": "POS收银机",
    "kds_display": "KDS厨显屏",
    "scale": "电子秤",
    "scanner": "扫码设备",
    "cash_drawer": "钱箱",
    "queue_machine": "排队叫号机",
    "kiosk": "自助点餐/结账机",
    "label_printer": "标签打印机",
    "network": "网络设备",
}

# ─── 硬件设备注册表 ───

DEVICE_REGISTRY: dict[str, dict] = {

    # ════════════════════════════════════════════
    # 热敏打印机（小票 / 厨打）
    # ════════════════════════════════════════════

    # --- 北洋(SNBC) ---
    "beiyang_98np": {
        "brand": "北洋(SNBC)",
        "model": "BTP-98NP",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet", "serial"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 230,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "收银小票",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "收银主力机型，稳定性高，国内餐饮装机量最大",
    },
    "beiyang_2002cp": {
        "brand": "北洋(SNBC)",
        "model": "BTP-2002CP",
        "category": "printer",
        "sub_type": "kitchen",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet", "serial"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 200,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "后厨打印",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "后厨专用，耐高温防油污，蜂鸣提醒",
    },
    "beiyang_r580ii": {
        "brand": "北洋(SNBC)",
        "model": "BTP-R580II",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 250,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "高速收银",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "高端收银机型，打印速度250mm/s",
    },

    # --- 佳博(Gainscha/Gprinter) ---
    "gainscha_c80180ii": {
        "brand": "佳博(Gprinter)",
        "model": "GP-C80180II",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet", "serial"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 250,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "收银小票",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "高速网口打印机，性价比高，餐饮市场占有率前三",
    },
    "gainscha_sd80s": {
        "brand": "佳博(Gprinter)",
        "model": "GP-SD80S",
        "category": "printer",
        "sub_type": "kitchen",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 200,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "后厨打印",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "经济型厨打，适合中小门店",
    },
    "gainscha_l80160i": {
        "brand": "佳博(Gprinter)",
        "model": "GP-L80160I",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet", "wifi"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 160,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "收银/厨打通用",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "支持WiFi直连，免布网线",
    },
    "gainscha_c80250ii": {
        "brand": "佳博(Gprinter)",
        "model": "GP-C80250II",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet", "serial"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 250,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "高速收银",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "佳博旗舰收银打印机",
    },

    # --- 爱普生(Epson) ---
    "epson_t88vi": {
        "brand": "爱普生(Epson)",
        "model": "TM-T88VI",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet", "serial", "bluetooth"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 350,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "高端收银",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "全球热敏打印机标杆，打印速度350mm/s，稳定性极佳，高端连锁首选",
    },
    "epson_t82iii": {
        "brand": "爱普生(Epson)",
        "model": "TM-T82III",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 250,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "收银小票",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "性价比款爱普生，中端连锁常用",
    },
    "epson_u220b": {
        "brand": "爱普生(Epson)",
        "model": "TM-U220B",
        "category": "printer",
        "sub_type": "kitchen",
        "paper_width_mm": 76,
        "interfaces": ["usb", "serial", "ethernet"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 98,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "后厨打印(针式)",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "针式厨打经典款，声音大提醒效果好，耐油污，适合重油厨房",
    },

    # --- 芯烨(XPrinter) ---
    "xprinter_n160ii": {
        "brand": "芯烨(XPrinter)",
        "model": "XP-N160II",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 160,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "经济型收银",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "高性价比，中小餐饮门店常用",
    },
    "xprinter_q200ii": {
        "brand": "芯烨(XPrinter)",
        "model": "XP-Q200II",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet", "wifi"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 200,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "收银/厨打通用",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "支持WiFi连接，中端机型",
    },

    # --- 容大(Rongda/RONGTA) ---
    "rongta_rp80": {
        "brand": "容大(RONGTA)",
        "model": "RP80",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["usb", "ethernet"],
        "protocol": "ESC/POS",
        "encoding": "GBK",
        "speed_mm_s": 250,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "收银小票",
        "connection_config": {"port": 9100, "type": "tcp"},
        "notes": "国产高性价比，外卖平台常见配套机型",
    },

    # --- 商米内置打印机 ---
    "sunmi_builtin_printer": {
        "brand": "商米(SUNMI)",
        "model": "内置打印机",
        "category": "printer",
        "sub_type": "receipt",
        "paper_width_mm": 80,
        "interfaces": ["sunmi_sdk"],
        "protocol": "SUNMI_JS_BRIDGE",
        "encoding": "GBK",
        "speed_mm_s": 200,
        "auto_cutter": True,
        "dpi": 203,
        "recommended_scene": "商米POS内置收银打印",
        "connection_config": {"type": "sunmi_bridge"},
        "notes": "商米T2/T2s/V2等机型内置打印机，通过JS Bridge调用",
    },

    # ════════════════════════════════════════════
    # POS收银机
    # ════════════════════════════════════════════

    # --- 商米(SUNMI) ---
    "sunmi_t2": {
        "brand": "商米(SUNMI)",
        "model": "T2",
        "category": "pos_terminal",
        "os": "Android 9.0",
        "screen": "15.6寸+10.1寸双屏",
        "cpu": "RK3399",
        "ram_gb": 2,
        "storage_gb": 16,
        "interfaces": ["wifi", "ethernet", "bluetooth", "usb"],
        "built_in_printer": True,
        "printer_width_mm": 80,
        "built_in_scanner": False,
        "peripherals": ["打印机", "扫码", "NFC"],
        "recommended_scene": "中大型门店收银",
        "notes": "商米旗舰双屏POS，中国餐饮SaaS装机量第一",
    },
    "sunmi_t2s": {
        "brand": "商米(SUNMI)",
        "model": "T2s",
        "category": "pos_terminal",
        "os": "Android 11",
        "screen": "15.6寸+10.1寸双屏",
        "cpu": "RK3566",
        "ram_gb": 4,
        "storage_gb": 32,
        "interfaces": ["wifi", "ethernet", "bluetooth", "usb"],
        "built_in_printer": True,
        "printer_width_mm": 80,
        "built_in_scanner": False,
        "peripherals": ["打印机", "扫码", "NFC"],
        "recommended_scene": "中大型门店收银",
        "notes": "T2升级版，更高性能，4GB内存",
    },
    "sunmi_v2_pro": {
        "brand": "商米(SUNMI)",
        "model": "V2 Pro",
        "category": "pos_terminal",
        "os": "Android 7.1",
        "screen": "5.99寸",
        "cpu": "Qualcomm MSM8953",
        "ram_gb": 2,
        "storage_gb": 16,
        "interfaces": ["wifi", "4g", "bluetooth", "usb"],
        "built_in_printer": True,
        "printer_width_mm": 58,
        "built_in_scanner": True,
        "peripherals": ["打印机", "扫码", "NFC"],
        "recommended_scene": "移动收银/外卖接单",
        "notes": "手持POS，适合轻量收银和外卖接单",
    },
    "sunmi_d3_mini": {
        "brand": "商米(SUNMI)",
        "model": "D3 Mini",
        "category": "pos_terminal",
        "os": "Android 10",
        "screen": "15.6寸单屏",
        "cpu": "RK3566",
        "ram_gb": 2,
        "storage_gb": 16,
        "interfaces": ["wifi", "ethernet", "bluetooth", "usb"],
        "built_in_printer": False,
        "built_in_scanner": False,
        "peripherals": ["外接打印机", "扫码枪"],
        "recommended_scene": "轻量门店收银",
        "notes": "经济型单屏POS，适合小型门店",
    },

    # --- 客如云(Keruyun) ---
    "keruyun_smart_pos": {
        "brand": "客如云(Keruyun)",
        "model": "智能收银一体机 D2",
        "category": "pos_terminal",
        "os": "Android 9.0",
        "screen": "15.6寸+10.1寸双屏",
        "cpu": "RK3399",
        "ram_gb": 2,
        "storage_gb": 16,
        "interfaces": ["wifi", "ethernet", "bluetooth", "usb"],
        "built_in_printer": True,
        "printer_width_mm": 80,
        "built_in_scanner": False,
        "peripherals": ["打印机", "扫码", "NFC"],
        "recommended_scene": "中大型门店收银",
        "notes": "阿里本地生活旗下，与饿了么/口碑深度整合",
    },
    "keruyun_mini_pos": {
        "brand": "客如云(Keruyun)",
        "model": "Mini收银机",
        "category": "pos_terminal",
        "os": "Android 9.0",
        "screen": "10.1寸单屏",
        "cpu": "RK3288",
        "ram_gb": 2,
        "storage_gb": 8,
        "interfaces": ["wifi", "ethernet", "usb"],
        "built_in_printer": True,
        "printer_width_mm": 58,
        "built_in_scanner": False,
        "peripherals": ["打印机"],
        "recommended_scene": "小型门店/奶茶店",
        "notes": "紧凑型收银机，适合台面空间有限的门店",
    },

    # --- 美团收银 ---
    "meituan_d1": {
        "brand": "美团",
        "model": "美团收银机 D1",
        "category": "pos_terminal",
        "os": "Android 9.0",
        "screen": "15.6寸+10.1寸双屏",
        "cpu": "RK3399",
        "ram_gb": 2,
        "storage_gb": 16,
        "interfaces": ["wifi", "ethernet", "bluetooth", "usb"],
        "built_in_printer": True,
        "printer_width_mm": 80,
        "built_in_scanner": False,
        "peripherals": ["打印机", "扫码"],
        "recommended_scene": "美团生态门店收银",
        "notes": "美团自有品牌收银机，深度整合美团外卖/团购",
    },

    # --- 中科英泰(INTECH) ---
    "intech_p10": {
        "brand": "中科英泰(INTECH)",
        "model": "POS-P10",
        "category": "pos_terminal",
        "os": "Windows 10 IoT",
        "screen": "15.6寸+10.1寸双屏",
        "cpu": "Intel J1900",
        "ram_gb": 4,
        "storage_gb": 64,
        "interfaces": ["wifi", "ethernet", "usb", "serial"],
        "built_in_printer": False,
        "built_in_scanner": False,
        "peripherals": ["外接打印机", "扫码枪", "钱箱"],
        "recommended_scene": "Windows收银(传统软件兼容)",
        "notes": "Windows POS机，兼容传统餐饮软件（思迅/科脉等）",
    },

    # ════════════════════════════════════════════
    # KDS 厨显屏
    # ════════════════════════════════════════════

    # --- 商米(SUNMI) ---
    "sunmi_d2s_kds": {
        "brand": "商米(SUNMI)",
        "model": "D2s (KDS模式)",
        "category": "kds_display",
        "os": "Android 10",
        "screen": "15.6寸",
        "resolution": "1920x1080",
        "cpu": "RK3566",
        "ram_gb": 2,
        "storage_gb": 16,
        "interfaces": ["wifi", "ethernet"],
        "touch_screen": True,
        "wall_mount": True,
        "recommended_scene": "后厨出餐显示",
        "notes": "商米平板做KDS，触控操作叫起/出餐，安卓生态兼容",
    },
    "sunmi_k2": {
        "brand": "商米(SUNMI)",
        "model": "K2",
        "category": "kds_display",
        "os": "Android 11",
        "screen": "21.5寸",
        "resolution": "1920x1080",
        "cpu": "RK3566",
        "ram_gb": 4,
        "storage_gb": 32,
        "interfaces": ["wifi", "ethernet"],
        "touch_screen": True,
        "wall_mount": True,
        "recommended_scene": "大型后厨KDS",
        "notes": "商米专业KDS大屏，21.5寸大屏清晰显示",
    },

    # --- 客如云(Keruyun) ---
    "keruyun_kds": {
        "brand": "客如云(Keruyun)",
        "model": "厨显屏 K1",
        "category": "kds_display",
        "os": "Android 9.0",
        "screen": "15.6寸",
        "resolution": "1920x1080",
        "cpu": "RK3288",
        "ram_gb": 2,
        "storage_gb": 8,
        "interfaces": ["wifi", "ethernet"],
        "touch_screen": True,
        "wall_mount": True,
        "recommended_scene": "后厨出餐显示",
        "notes": "客如云自有KDS硬件，与客如云POS深度联动",
    },

    # --- 通用安卓平板方案 ---
    "generic_android_kds": {
        "brand": "通用安卓平板",
        "model": "15.6寸商用平板",
        "category": "kds_display",
        "os": "Android 10+",
        "screen": "15.6寸",
        "resolution": "1920x1080",
        "cpu": "RK3288/RK3399",
        "ram_gb": 2,
        "storage_gb": 16,
        "interfaces": ["wifi", "ethernet"],
        "touch_screen": True,
        "wall_mount": True,
        "recommended_scene": "后厨出餐显示(通用方案)",
        "notes": "华为/联想等品牌商用平板，安装Chrome运行Web KDS",
    },

    # ════════════════════════════════════════════
    # 电子秤
    # ════════════════════════════════════════════

    # --- 顶尖(Digi) ---
    "digi_sm5300": {
        "brand": "顶尖(DIGI)",
        "model": "SM-5300",
        "category": "scale",
        "max_weight_kg": 30,
        "min_division_g": 5,
        "interfaces": ["serial_rs232", "usb"],
        "protocol": "DIGI_SERIAL",
        "baudrate": 9600,
        "data_bits": 8,
        "stop_bits": 1,
        "parity": "none",
        "display": "LED双面显示",
        "label_printer": True,
        "recommended_scene": "称重菜收银",
        "notes": "日本品牌，精度高，连锁餐饮称重菜行业标准",
    },
    "digi_sm110": {
        "brand": "顶尖(DIGI)",
        "model": "SM-110",
        "category": "scale",
        "max_weight_kg": 15,
        "min_division_g": 5,
        "interfaces": ["serial_rs232", "ethernet"],
        "protocol": "DIGI_SERIAL",
        "baudrate": 9600,
        "data_bits": 8,
        "stop_bits": 1,
        "parity": "none",
        "display": "LCD触摸屏",
        "label_printer": True,
        "recommended_scene": "自助称重/标签打印",
        "notes": "触摸屏操作，可直接打印标签",
    },

    # --- 大华(Dahua) ---
    "dahua_tm30": {
        "brand": "大华(Dahua)",
        "model": "TM-30",
        "category": "scale",
        "max_weight_kg": 30,
        "min_division_g": 5,
        "interfaces": ["serial_rs232", "usb"],
        "protocol": "DAHUA_SERIAL",
        "baudrate": 9600,
        "data_bits": 8,
        "stop_bits": 1,
        "parity": "none",
        "display": "LED双面显示",
        "label_printer": False,
        "recommended_scene": "称重菜收银",
        "notes": "国产高性价比，餐饮称重菜常用",
    },
    "dahua_tm15": {
        "brand": "大华(Dahua)",
        "model": "TM-15",
        "category": "scale",
        "max_weight_kg": 15,
        "min_division_g": 2,
        "interfaces": ["serial_rs232", "usb"],
        "protocol": "DAHUA_SERIAL",
        "baudrate": 9600,
        "data_bits": 8,
        "stop_bits": 1,
        "parity": "none",
        "display": "LED显示",
        "label_printer": False,
        "recommended_scene": "小份称重",
        "notes": "紧凑型，适合吧台称重",
    },

    # --- 凯士(CAS) ---
    "cas_sw_ii": {
        "brand": "凯士(CAS)",
        "model": "SW-II",
        "category": "scale",
        "max_weight_kg": 30,
        "min_division_g": 5,
        "interfaces": ["serial_rs232"],
        "protocol": "CAS_SERIAL",
        "baudrate": 9600,
        "data_bits": 8,
        "stop_bits": 1,
        "parity": "none",
        "display": "LED双面显示",
        "label_printer": False,
        "recommended_scene": "称重菜收银",
        "notes": "韩国品牌，全球出货量领先，耐用稳定",
    },

    # --- 梅特勒-托利多(Mettler Toledo) ---
    "mettler_bba231": {
        "brand": "梅特勒-托利多(Mettler Toledo)",
        "model": "bba231",
        "category": "scale",
        "max_weight_kg": 30,
        "min_division_g": 5,
        "interfaces": ["serial_rs232", "ethernet"],
        "protocol": "MT_SICS",
        "baudrate": 9600,
        "data_bits": 8,
        "stop_bits": 1,
        "parity": "none",
        "display": "LCD背光",
        "label_printer": False,
        "recommended_scene": "高精度称重",
        "notes": "瑞士品牌，高端连锁和中央厨房使用",
    },

    # ════════════════════════════════════════════
    # 扫码设备（扫码枪 / 扫码盒）
    # ════════════════════════════════════════════

    # --- 新大陆(Newland) ---
    "newland_fr80": {
        "brand": "新大陆(Newland)",
        "model": "FR80",
        "category": "scanner",
        "sub_type": "box",
        "scan_type": ["1D", "2D"],
        "interfaces": ["usb_hid", "serial"],
        "protocol": "HID_KEYBOARD",
        "scan_speed_ms": 50,
        "support_screen_scan": True,
        "recommended_scene": "收银台支付扫码",
        "notes": "桌面式扫码盒，支持手机屏幕扫码，餐饮收银标配",
    },
    "newland_hr22": {
        "brand": "新大陆(Newland)",
        "model": "HR22 Dorada",
        "category": "scanner",
        "sub_type": "gun",
        "scan_type": ["1D", "2D"],
        "interfaces": ["usb_hid"],
        "protocol": "HID_KEYBOARD",
        "scan_speed_ms": 40,
        "support_screen_scan": True,
        "recommended_scene": "手持扫码",
        "notes": "有线扫码枪，性价比高，国产扫码设备龙头",
    },
    "newland_bs80": {
        "brand": "新大陆(Newland)",
        "model": "BS80 Piranha",
        "category": "scanner",
        "sub_type": "box",
        "scan_type": ["1D", "2D"],
        "interfaces": ["usb_hid", "serial"],
        "protocol": "HID_KEYBOARD",
        "scan_speed_ms": 30,
        "support_screen_scan": True,
        "recommended_scene": "高频收银扫码",
        "notes": "高速扫码盒，大窗口，适合高峰期",
    },

    # --- 霍尼韦尔(Honeywell) ---
    "honeywell_yj_hf600": {
        "brand": "霍尼韦尔(Honeywell)",
        "model": "YJ-HF600",
        "category": "scanner",
        "sub_type": "box",
        "scan_type": ["1D", "2D"],
        "interfaces": ["usb_hid", "serial"],
        "protocol": "HID_KEYBOARD",
        "scan_speed_ms": 30,
        "support_screen_scan": True,
        "recommended_scene": "收银台扫码",
        "notes": "全球扫码设备第一品牌，高端连锁首选",
    },
    "honeywell_1900g": {
        "brand": "霍尼韦尔(Honeywell)",
        "model": "Xenon 1900g",
        "category": "scanner",
        "sub_type": "gun",
        "scan_type": ["1D", "2D"],
        "interfaces": ["usb_hid", "serial"],
        "protocol": "HID_KEYBOARD",
        "scan_speed_ms": 30,
        "support_screen_scan": True,
        "recommended_scene": "手持扫码",
        "notes": "工业级扫码枪，耐摔耐用",
    },

    # --- 斑马(Zebra) ---
    "zebra_ds9308": {
        "brand": "斑马(Zebra)",
        "model": "DS9308",
        "category": "scanner",
        "sub_type": "box",
        "scan_type": ["1D", "2D"],
        "interfaces": ["usb_hid"],
        "protocol": "HID_KEYBOARD",
        "scan_speed_ms": 30,
        "support_screen_scan": True,
        "recommended_scene": "收银台扫码",
        "notes": "原Motorola Symbol产品线，餐饮连锁装机量大",
    },

    # --- 商米内置扫码 ---
    "sunmi_builtin_scanner": {
        "brand": "商米(SUNMI)",
        "model": "内置扫码头",
        "category": "scanner",
        "sub_type": "built_in",
        "scan_type": ["1D", "2D"],
        "interfaces": ["sunmi_sdk"],
        "protocol": "SUNMI_JS_BRIDGE",
        "scan_speed_ms": 50,
        "support_screen_scan": True,
        "recommended_scene": "商米POS内置扫码",
        "notes": "商米V2 Pro等手持设备内置扫码头",
    },

    # ════════════════════════════════════════════
    # 钱箱
    # ════════════════════════════════════════════

    "cash_drawer_405": {
        "brand": "通用",
        "model": "405型三档钱箱",
        "category": "cash_drawer",
        "size": "405x420x100mm",
        "compartments_bill": 4,
        "compartments_coin": 5,
        "trigger": "ESC_P",
        "interfaces": ["rj11_printer"],
        "protocol": "ESC_P_TRIGGER",
        "recommended_scene": "收银台现金收银",
        "notes": "通过打印机RJ11接口连接，ESC p指令触发弹开",
    },
    "cash_drawer_335": {
        "brand": "通用",
        "model": "335型迷你钱箱",
        "category": "cash_drawer",
        "size": "335x340x100mm",
        "compartments_bill": 3,
        "compartments_coin": 5,
        "trigger": "ESC_P",
        "interfaces": ["rj11_printer"],
        "protocol": "ESC_P_TRIGGER",
        "recommended_scene": "小型门店收银",
        "notes": "紧凑型钱箱，台面空间有限时使用",
    },
    "sunmi_cash_drawer": {
        "brand": "商米(SUNMI)",
        "model": "商米钱箱",
        "category": "cash_drawer",
        "size": "420x420x100mm",
        "compartments_bill": 5,
        "compartments_coin": 8,
        "trigger": "SUNMI_SDK",
        "interfaces": ["usb"],
        "protocol": "SUNMI_JS_BRIDGE",
        "recommended_scene": "商米POS配套钱箱",
        "notes": "商米POS专用钱箱，USB直连，通过SDK控制",
    },

    # ════════════════════════════════════════════
    # 排队叫号机
    # ════════════════════════════════════════════

    "meiou_qms": {
        "brand": "美欧(MEIOU)",
        "model": "QMS-200",
        "category": "queue_machine",
        "os": "Android 9.0",
        "screen": "15.6寸触摸屏",
        "interfaces": ["wifi", "ethernet"],
        "protocol": "HTTP_API",
        "printer_width_mm": 80,
        "voice_broadcast": True,
        "recommended_scene": "门店排队取号",
        "notes": "支持微信扫码取号、语音叫号、短信通知",
    },
    "yijiahe_qt90": {
        "brand": "易嘉和(YIJIAHE)",
        "model": "QT90",
        "category": "queue_machine",
        "os": "Android 10",
        "screen": "21.5寸触摸屏",
        "interfaces": ["wifi", "ethernet"],
        "protocol": "HTTP_API",
        "printer_width_mm": 80,
        "voice_broadcast": True,
        "recommended_scene": "大型门店排队叫号",
        "notes": "大屏排队机，支持多业务类型排队（堂食/外带）",
    },
    "sunmi_queue": {
        "brand": "商米(SUNMI)",
        "model": "商米排队叫号方案",
        "category": "queue_machine",
        "os": "Android 11",
        "screen": "15.6寸",
        "interfaces": ["wifi", "ethernet"],
        "protocol": "HTTP_API",
        "printer_width_mm": 80,
        "voice_broadcast": True,
        "recommended_scene": "门店排队取号",
        "notes": "基于商米D系列平板+排队APP实现",
    },

    # ════════════════════════════════════════════
    # 自助点餐机 / 自助结账机
    # ════════════════════════════════════════════

    "sunmi_kiosk_k2": {
        "brand": "商米(SUNMI)",
        "model": "K2 自助点餐机",
        "category": "kiosk",
        "os": "Android 11",
        "screen": "21.5寸触摸屏",
        "resolution": "1920x1080",
        "interfaces": ["wifi", "ethernet", "usb"],
        "built_in_printer": True,
        "printer_width_mm": 80,
        "built_in_scanner": True,
        "payment": ["微信", "支付宝", "银联闪付"],
        "recommended_scene": "快餐/茶饮自助点餐",
        "notes": "商米自助点餐解决方案，一体化设计",
    },
    "keruyun_kiosk": {
        "brand": "客如云(Keruyun)",
        "model": "自助点餐机 Z1",
        "category": "kiosk",
        "os": "Android 9.0",
        "screen": "21.5寸触摸屏",
        "resolution": "1920x1080",
        "interfaces": ["wifi", "ethernet"],
        "built_in_printer": True,
        "printer_width_mm": 80,
        "built_in_scanner": True,
        "payment": ["微信", "支付宝", "刷脸支付"],
        "recommended_scene": "快餐自助点餐",
        "notes": "客如云自助设备，支持刷脸支付",
    },
    "meituan_kiosk": {
        "brand": "美团",
        "model": "美团自助点餐机",
        "category": "kiosk",
        "os": "Android 9.0",
        "screen": "21.5寸/27寸触摸屏",
        "resolution": "1920x1080",
        "interfaces": ["wifi", "ethernet"],
        "built_in_printer": True,
        "printer_width_mm": 80,
        "built_in_scanner": True,
        "payment": ["微信", "支付宝", "美团支付"],
        "recommended_scene": "快餐连锁自助点餐",
        "notes": "美团自有品牌自助机，与美团生态深度整合",
    },

    # ════════════════════════════════════════════
    # 标签打印机
    # ════════════════════════════════════════════

    # --- 斑马(Zebra) ---
    "zebra_gk888t": {
        "brand": "斑马(Zebra)",
        "model": "GK888t",
        "category": "label_printer",
        "print_method": "热转印/热敏",
        "label_width_mm": 104,
        "dpi": 203,
        "speed_mm_s": 102,
        "interfaces": ["usb", "ethernet"],
        "protocol": "ZPL",
        "recommended_scene": "菜品标签/中央厨房标签",
        "notes": "全球标签打印机标杆，ZPL指令集，中央厨房和门店均适用",
    },
    "zebra_zt230": {
        "brand": "斑马(Zebra)",
        "model": "ZT230",
        "category": "label_printer",
        "print_method": "热转印/热敏",
        "label_width_mm": 114,
        "dpi": 203,
        "speed_mm_s": 152,
        "interfaces": ["usb", "ethernet", "serial"],
        "protocol": "ZPL",
        "recommended_scene": "中央厨房大批量标签",
        "notes": "工业级标签打印机，适合中央厨房高产量标签打印",
    },

    # --- 得力(Deli) ---
    "deli_dl_888b": {
        "brand": "得力(Deli)",
        "model": "DL-888B",
        "category": "label_printer",
        "print_method": "热敏",
        "label_width_mm": 108,
        "dpi": 203,
        "speed_mm_s": 127,
        "interfaces": ["usb"],
        "protocol": "TSPL",
        "recommended_scene": "菜品标签/价签",
        "notes": "国产高性价比标签打印机，门店菜品标签常用",
    },

    # --- 精臣(Niimbot) ---
    "niimbot_d11": {
        "brand": "精臣(Niimbot)",
        "model": "D11",
        "category": "label_printer",
        "print_method": "热敏",
        "label_width_mm": 15,
        "dpi": 203,
        "speed_mm_s": 30,
        "interfaces": ["bluetooth"],
        "protocol": "NIIMBOT_BLE",
        "recommended_scene": "便携标签/食材标签",
        "notes": "便携式蓝牙标签机，适合厨房食材日期标签",
    },

    # --- 佳博(Gprinter) ---
    "gainscha_gp1324d": {
        "brand": "佳博(Gprinter)",
        "model": "GP-1324D",
        "category": "label_printer",
        "print_method": "热敏",
        "label_width_mm": 104,
        "dpi": 203,
        "speed_mm_s": 127,
        "interfaces": ["usb", "ethernet"],
        "protocol": "TSPL",
        "recommended_scene": "菜品标签/外卖标签",
        "notes": "热敏标签打印机，免碳带，适合门店标签打印",
    },

    # ════════════════════════════════════════════
    # 网络设备
    # ════════════════════════════════════════════

    # --- 路由器 ---
    "huawei_ar161": {
        "brand": "华为(Huawei)",
        "model": "AR161",
        "category": "network",
        "sub_type": "router",
        "wan_ports": 1,
        "lan_ports": 4,
        "wifi": False,
        "throughput_mbps": 1000,
        "recommended_scene": "门店主路由",
        "notes": "企业级路由器，VLAN隔离收银网和客用网，稳定性高",
    },
    "ikuai_r3g": {
        "brand": "爱快(iKuai)",
        "model": "IK-R3G",
        "category": "network",
        "sub_type": "router",
        "wan_ports": 2,
        "lan_ports": 4,
        "wifi": False,
        "throughput_mbps": 1000,
        "recommended_scene": "门店主路由(多WAN)",
        "notes": "多WAN口路由器，支持双线接入，连锁餐饮常用",
    },

    # --- 交换机 ---
    "h3c_s1208": {
        "brand": "新华三(H3C)",
        "model": "S1208",
        "category": "network",
        "sub_type": "switch",
        "ports": 8,
        "speed_mbps": 1000,
        "poe": False,
        "managed": False,
        "recommended_scene": "门店接入层交换机",
        "notes": "8口千兆交换机，连接POS/打印机/KDS等设备",
    },
    "h3c_s1224": {
        "brand": "新华三(H3C)",
        "model": "S1224",
        "category": "network",
        "sub_type": "switch",
        "ports": 24,
        "speed_mbps": 1000,
        "poe": False,
        "managed": False,
        "recommended_scene": "大型门店汇聚交换机",
        "notes": "24口千兆交换机，大型门店多设备接入",
    },

    # --- 无线AP ---
    "huawei_ap4050dn": {
        "brand": "华为(Huawei)",
        "model": "AP4050DN",
        "category": "network",
        "sub_type": "wireless_ap",
        "wifi_standard": "WiFi 5 (802.11ac)",
        "max_speed_mbps": 1167,
        "poe_powered": True,
        "concurrent_users": 64,
        "recommended_scene": "门店无线覆盖",
        "notes": "企业级吸顶AP，收银网与客用网SSID隔离",
    },
    "ruijie_ap820": {
        "brand": "锐捷(Ruijie)",
        "model": "RG-AP820-L(V3)",
        "category": "network",
        "sub_type": "wireless_ap",
        "wifi_standard": "WiFi 6 (802.11ax)",
        "max_speed_mbps": 2976,
        "poe_powered": True,
        "concurrent_users": 100,
        "recommended_scene": "门店无线覆盖(WiFi6)",
        "notes": "WiFi6吸顶AP，连锁餐饮部署量大，支持云管理",
    },
    "tplink_ap1900gc": {
        "brand": "TP-LINK",
        "model": "TL-AP1900GC-PoE",
        "category": "network",
        "sub_type": "wireless_ap",
        "wifi_standard": "WiFi 5 (802.11ac)",
        "max_speed_mbps": 1900,
        "poe_powered": True,
        "concurrent_users": 64,
        "recommended_scene": "经济型门店无线覆盖",
        "notes": "性价比之选，中小门店WiFi覆盖",
    },
}


# ─── 便捷查询函数 ───

def get_devices_by_category(category: str) -> dict[str, dict]:
    """按品类筛选设备。

    Args:
        category: 品类标识，见 DEVICE_CATEGORIES

    Returns:
        该品类下的所有设备字典
    """
    return {
        key: dev for key, dev in DEVICE_REGISTRY.items()
        if dev.get("category") == category
    }


def get_device(device_key: str) -> dict:
    """获取单个设备信息。

    Args:
        device_key: 设备标识

    Returns:
        设备配置字典

    Raises:
        ValueError: 设备不存在
    """
    device = DEVICE_REGISTRY.get(device_key)
    if device is None:
        raise ValueError(
            f"设备不存在: {device_key}，"
            f"可用设备: {', '.join(DEVICE_REGISTRY.keys())}"
        )
    return device


def search_devices(
    brand: str | None = None,
    category: str | None = None,
    interface: str | None = None,
    protocol: str | None = None,
) -> dict[str, dict]:
    """多条件搜索设备。

    Args:
        brand: 品牌关键词（模糊匹配）
        category: 品类标识
        interface: 接口类型（精确匹配）
        protocol: 协议类型（精确匹配）

    Returns:
        匹配的设备字典
    """
    results = {}
    for key, dev in DEVICE_REGISTRY.items():
        if category and dev.get("category") != category:
            continue
        if brand and brand.lower() not in dev.get("brand", "").lower():
            continue
        if interface and interface not in dev.get("interfaces", []):
            continue
        if protocol and dev.get("protocol") != protocol:
            continue
        results[key] = dev
    return results


def get_all_brands(category: str | None = None) -> list[str]:
    """获取所有品牌列表。

    Args:
        category: 可选，按品类筛选

    Returns:
        去重后的品牌列表
    """
    brands = set()
    for dev in DEVICE_REGISTRY.values():
        if category and dev.get("category") != category:
            continue
        brands.add(dev.get("brand", "未知"))
    return sorted(brands)


def get_recommended_config(store_size: str = "medium") -> dict[str, list[str]]:
    """获取推荐门店硬件配置方案。

    Args:
        store_size: 门店规模 small / medium / large

    Returns:
        各品类推荐设备key列表
    """
    configs = {
        "small": {
            "pos_terminal": ["sunmi_d3_mini"],
            "printer": ["gainscha_sd80s"],
            "scanner": ["newland_fr80"],
            "cash_drawer": ["cash_drawer_335"],
            "network": ["ikuai_r3g", "tplink_ap1900gc"],
        },
        "medium": {
            "pos_terminal": ["sunmi_t2"],
            "printer": ["beiyang_98np", "gainscha_sd80s"],
            "kds_display": ["sunmi_d2s_kds"],
            "scanner": ["newland_fr80"],
            "cash_drawer": ["cash_drawer_405"],
            "label_printer": ["deli_dl_888b"],
            "network": ["ikuai_r3g", "h3c_s1208", "ruijie_ap820"],
        },
        "large": {
            "pos_terminal": ["sunmi_t2s", "sunmi_t2s"],
            "printer": ["epson_t88vi", "beiyang_2002cp", "beiyang_2002cp"],
            "kds_display": ["sunmi_k2", "sunmi_d2s_kds"],
            "scale": ["digi_sm5300"],
            "scanner": ["honeywell_yj_hf600", "honeywell_yj_hf600"],
            "cash_drawer": ["cash_drawer_405", "cash_drawer_405"],
            "queue_machine": ["yijiahe_qt90"],
            "kiosk": ["sunmi_kiosk_k2"],
            "label_printer": ["zebra_gk888t"],
            "network": ["huawei_ar161", "h3c_s1224", "huawei_ap4050dn", "huawei_ap4050dn"],
        },
    }
    return configs.get(store_size, configs["medium"])
