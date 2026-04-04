"""OWASP Top 10 输入验证工具 -- 完整测试套件

覆盖范围：
- validators.py：所有验证/清理函数
- sql_guard.py：SQL 注入检测（15+ 种攻击模式）
- xss_guard.py：XSS 检测（10+ 种攻击模式）
"""

import pytest

from shared.security.src.validators import (
    sanitize_string,
    validate_uuid,
    validate_phone,
    validate_email,
    sanitize_filename,
    validate_url,
    sanitize_html,
    validate_amount_fen,
    validate_page_params,
    validate_date_range,
)
from shared.security.src.sql_guard import check_sql_injection, sanitize_for_like
from shared.security.src.xss_guard import escape_html, validate_no_script, get_csp_header


# ===========================================================================
# sanitize_string
# ===========================================================================


class TestSanitizeString:
    def test_normal_string(self) -> None:
        assert sanitize_string("hello world") == "hello world"

    def test_strips_control_chars(self) -> None:
        assert sanitize_string("hello\x00world\x07") == "helloworld"

    def test_preserves_newline_and_tab(self) -> None:
        # \n (\x0a) 和 \t (\x09) 不在控制字符范围内，应保留
        result = sanitize_string("line1\nline2\tcol")
        assert "\n" in result
        assert "\t" in result

    def test_truncates_to_max_length(self) -> None:
        long = "a" * 1000
        assert len(sanitize_string(long, max_length=50)) == 50

    def test_custom_max_length(self) -> None:
        assert sanitize_string("abcdef", max_length=3) == "abc"

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="expected str"):
            sanitize_string(123)  # type: ignore[arg-type]

    def test_empty_string(self) -> None:
        assert sanitize_string("") == ""

    def test_unicode(self) -> None:
        assert sanitize_string("你好世界") == "你好世界"


# ===========================================================================
# validate_uuid
# ===========================================================================


class TestValidateUUID:
    def test_valid_uuid4(self) -> None:
        uid = "550e8400-e29b-41d4-a716-446655440000"
        assert validate_uuid(uid) == uid

    def test_valid_uuid_no_dashes(self) -> None:
        # uuid.UUID 也接受无连字符格式
        result = validate_uuid("550e8400e29b41d4a716446655440000")
        assert "-" in result  # 返回标准格式

    def test_invalid_uuid(self) -> None:
        with pytest.raises(ValueError, match="invalid UUID"):
            validate_uuid("not-a-uuid")

    def test_sql_injection_in_uuid(self) -> None:
        with pytest.raises(ValueError, match="invalid UUID"):
            validate_uuid("'; DROP TABLE users; --")

    def test_empty_string(self) -> None:
        with pytest.raises(ValueError, match="invalid UUID"):
            validate_uuid("")


# ===========================================================================
# validate_phone
# ===========================================================================


class TestValidatePhone:
    def test_valid_phones(self) -> None:
        assert validate_phone("13800138000") == "13800138000"
        assert validate_phone("19912345678") == "19912345678"

    def test_strips_spaces_and_dashes(self) -> None:
        assert validate_phone("138-0013-8000") == "13800138000"
        assert validate_phone("138 0013 8000") == "13800138000"

    def test_invalid_prefix(self) -> None:
        with pytest.raises(ValueError, match="invalid phone"):
            validate_phone("12345678901")  # 12 开头无效

    def test_too_short(self) -> None:
        with pytest.raises(ValueError, match="invalid phone"):
            validate_phone("1380013800")

    def test_too_long(self) -> None:
        with pytest.raises(ValueError, match="invalid phone"):
            validate_phone("138001380001")

    def test_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="invalid phone"):
            validate_phone("1380013800a")


# ===========================================================================
# validate_email
# ===========================================================================


class TestValidateEmail:
    def test_valid_emails(self) -> None:
        assert validate_email("user@example.com") == "user@example.com"
        assert validate_email("User.Name+tag@Domain.CO") == "user.name+tag@domain.co"

    def test_invalid_emails(self) -> None:
        invalid = ["", "not-email", "@domain.com", "user@", "user@.com", "a@b.c"]
        for email in invalid:
            with pytest.raises(ValueError, match="invalid email"):
                validate_email(email)

    def test_too_long(self) -> None:
        long_email = "a" * 250 + "@b.com"
        with pytest.raises(ValueError, match="invalid email"):
            validate_email(long_email)


# ===========================================================================
# sanitize_filename
# ===========================================================================


class TestSanitizeFilename:
    def test_normal_filename(self) -> None:
        assert sanitize_filename("report.pdf") == "report.pdf"

    def test_chinese_filename(self) -> None:
        assert sanitize_filename("报表.xlsx") == "报表.xlsx"

    def test_path_traversal_dot_dot(self) -> None:
        result = sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_path_traversal_backslash(self) -> None:
        result = sanitize_filename("..\\..\\windows\\system32")
        assert ".." not in result
        assert "\\" not in result

    def test_strips_directory_path(self) -> None:
        assert sanitize_filename("/var/log/secret.txt") == "secret.txt"

    def test_removes_leading_dot(self) -> None:
        result = sanitize_filename(".htaccess")
        assert not result.startswith(".")

    def test_empty_after_sanitize_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            sanitize_filename("../../")

    def test_special_chars_replaced(self) -> None:
        result = sanitize_filename("file name@#$.txt")
        assert "@" not in result
        assert "#" not in result
        assert "$" not in result


# ===========================================================================
# validate_url
# ===========================================================================


class TestValidateUrl:
    def test_valid_https_url(self) -> None:
        url = "https://example.com/path?q=1"
        assert validate_url(url) == url

    def test_valid_http_url(self) -> None:
        assert validate_url("http://example.com") == "http://example.com"

    def test_invalid_scheme_ftp(self) -> None:
        with pytest.raises(ValueError, match="invalid URL scheme"):
            validate_url("ftp://example.com")

    def test_invalid_scheme_javascript(self) -> None:
        with pytest.raises(ValueError, match="invalid URL scheme"):
            validate_url("javascript:alert(1)")

    def test_ssrf_localhost(self) -> None:
        with pytest.raises(ValueError, match="internal host blocked"):
            validate_url("http://localhost/admin")

    def test_ssrf_internal_ip(self) -> None:
        with pytest.raises(ValueError, match="internal IP blocked"):
            validate_url("http://192.168.1.1/admin")
        with pytest.raises(ValueError, match="internal IP blocked"):
            validate_url("http://10.0.0.1/secret")
        with pytest.raises(ValueError, match="internal IP blocked"):
            validate_url("http://127.0.0.1/admin")

    def test_ssrf_metadata(self) -> None:
        with pytest.raises(ValueError, match="internal host blocked"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_ssrf_internal_domain(self) -> None:
        with pytest.raises(ValueError, match="internal host blocked"):
            validate_url("http://service.internal/api")

    def test_allowed_hosts(self) -> None:
        assert validate_url(
            "https://cdn.example.com/img.jpg",
            allowed_hosts=["cdn.example.com"],
        )

    def test_host_not_in_allowed_list(self) -> None:
        with pytest.raises(ValueError, match="not in allowed list"):
            validate_url(
                "https://evil.com/payload",
                allowed_hosts=["cdn.example.com"],
            )

    def test_missing_hostname(self) -> None:
        with pytest.raises(ValueError, match="missing hostname"):
            validate_url("http://")


# ===========================================================================
# sanitize_html
# ===========================================================================


class TestSanitizeHtml:
    def test_preserves_allowed_tags(self) -> None:
        assert sanitize_html("<b>bold</b>") == "<b>bold</b>"
        assert sanitize_html("<em>italic</em>") == "<em>italic</em>"

    def test_strips_script_tag(self) -> None:
        result = sanitize_html("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "alert(1)" in result

    def test_strips_attributes(self) -> None:
        result = sanitize_html('<b class="x" onclick="evil()">text</b>')
        assert result == "<b>text</b>"

    def test_strips_img_tag(self) -> None:
        result = sanitize_html('<img src=x onerror=alert(1)>')
        assert "<img" not in result

    def test_plain_text_unchanged(self) -> None:
        assert sanitize_html("hello world") == "hello world"

    def test_nested_tags(self) -> None:
        result = sanitize_html("<p><b>bold</b></p>")
        assert result == "<p><b>bold</b></p>"


# ===========================================================================
# validate_amount_fen
# ===========================================================================


class TestValidateAmountFen:
    def test_zero(self) -> None:
        assert validate_amount_fen(0) == 0

    def test_normal_amount(self) -> None:
        assert validate_amount_fen(9900) == 9900  # 99 元

    def test_max_amount(self) -> None:
        assert validate_amount_fen(10_000_000_00) == 10_000_000_00

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            validate_amount_fen(-1)

    def test_exceeds_max_raises(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            validate_amount_fen(10_000_000_01)

    def test_non_int_raises(self) -> None:
        with pytest.raises(ValueError, match="must be int"):
            validate_amount_fen(99.5)  # type: ignore[arg-type]


# ===========================================================================
# validate_page_params
# ===========================================================================


class TestValidatePageParams:
    def test_normal(self) -> None:
        assert validate_page_params(1, 20) == (1, 20)

    def test_max_size(self) -> None:
        assert validate_page_params(1, 100) == (1, 100)

    def test_page_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="page must be >= 1"):
            validate_page_params(0, 20)

    def test_negative_page_raises(self) -> None:
        with pytest.raises(ValueError, match="page must be >= 1"):
            validate_page_params(-1, 20)

    def test_size_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="size must be between"):
            validate_page_params(1, 0)

    def test_size_too_large_raises(self) -> None:
        with pytest.raises(ValueError, match="size must be between"):
            validate_page_params(1, 101)


# ===========================================================================
# validate_date_range
# ===========================================================================


class TestValidateDateRange:
    def test_normal(self) -> None:
        assert validate_date_range("2026-01-01", "2026-03-31") == (
            "2026-01-01",
            "2026-03-31",
        )

    def test_same_day(self) -> None:
        assert validate_date_range("2026-04-01", "2026-04-01") == (
            "2026-04-01",
            "2026-04-01",
        )

    def test_start_after_end_raises(self) -> None:
        with pytest.raises(ValueError, match="start date must be <= end"):
            validate_date_range("2026-12-01", "2026-01-01")

    def test_exceeds_one_year_raises(self) -> None:
        with pytest.raises(ValueError, match="exceeds 1 year"):
            validate_date_range("2025-01-01", "2026-01-02")

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid date format"):
            validate_date_range("01-01-2026", "2026-03-31")

    def test_exactly_one_year(self) -> None:
        # 365 天恰好在限制内
        assert validate_date_range("2026-01-01", "2027-01-01") == (
            "2026-01-01",
            "2027-01-01",
        )


# ===========================================================================
# SQL 注入检测 (sql_guard)
# ===========================================================================


class TestCheckSqlInjection:
    """15+ 种常见 SQL 注入攻击模式检测。"""

    @pytest.mark.parametrize(
        "payload",
        [
            # 经典注入
            "' OR 1=1 --",
            '" OR 1=1 --',
            "' AND 1=1",
            # 命令注入
            "; DROP TABLE users; --",
            "; DELETE FROM orders",
            "; UPDATE users SET role='admin'",
            "; INSERT INTO admins VALUES('hacker')",
            "; ALTER TABLE users ADD COLUMN pwned TEXT",
            # UNION 注入
            "UNION SELECT username, password FROM users",
            "UNION ALL SELECT 1,2,3",
            # 时间盲注
            "SLEEP(5)",
            "BENCHMARK(1000000, SHA1('test'))",
            "WAITFOR DELAY '0:0:5'",
            # 文件操作
            "LOAD_FILE('/etc/passwd')",
            "INTO OUTFILE '/tmp/pwned'",
            # 信息泄露
            "SELECT * FROM INFORMATION_SCHEMA.TABLES",
            # 编码绕过
            "CHAR(65)",
            "CONCAT('a','b')",
            # SQL Server 特有
            "xp_cmdshell",
            # 注释
            "admin'--",
            "admin /* comment */",
        ],
        ids=lambda p: p[:30],
    )
    def test_detects_injection(self, payload: str) -> None:
        assert check_sql_injection(payload) is True, f"missed: {payload}"

    @pytest.mark.parametrize(
        "safe_input",
        [
            "正常用户名",
            "hello world",
            "user@example.com",
            "John O'Brien",  # 单引号但无注入模式
            "100% organic",
            "2026-04-01",
            "SELECT 产品类型",  # 中文语境中的 SELECT 不匹配模式
        ],
    )
    def test_allows_safe_input(self, safe_input: str) -> None:
        assert check_sql_injection(safe_input) is False, f"false positive: {safe_input}"

    def test_non_string_returns_false(self) -> None:
        assert check_sql_injection(123) is False  # type: ignore[arg-type]


class TestSanitizeForLike:
    def test_escapes_percent(self) -> None:
        assert sanitize_for_like("100%") == r"100\%"

    def test_escapes_underscore(self) -> None:
        assert sanitize_for_like("user_name") == r"user\_name"

    def test_escapes_backslash(self) -> None:
        assert sanitize_for_like("path\\file") == "path\\\\file"

    def test_normal_string_unchanged(self) -> None:
        assert sanitize_for_like("hello") == "hello"

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="expected str"):
            sanitize_for_like(42)  # type: ignore[arg-type]


# ===========================================================================
# XSS 防护 (xss_guard)
# ===========================================================================


class TestEscapeHtml:
    def test_escapes_angle_brackets(self) -> None:
        assert escape_html("<script>") == "&lt;script&gt;"

    def test_escapes_ampersand(self) -> None:
        assert escape_html("a & b") == "a &amp; b"

    def test_escapes_quotes(self) -> None:
        result = escape_html('"hello" \'world\'')
        assert "&quot;" in result
        assert "&#x27;" in result

    def test_plain_text_unchanged(self) -> None:
        assert escape_html("hello world") == "hello world"

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="expected str"):
            escape_html(123)  # type: ignore[arg-type]


class TestValidateNoScript:
    """10+ 种 XSS 攻击模式检测。"""

    @pytest.mark.parametrize(
        "payload",
        [
            "<script>alert(1)</script>",
            "<SCRIPT>alert(1)</SCRIPT>",
            "<script src='evil.js'>",
            "< script >alert(1)</ script >",
            "javascript:alert(1)",
            "JAVASCRIPT:alert(document.cookie)",
            '<img onerror="alert(1)">',
            '<div onmouseover="steal()">',
            '<body onload="evil()">',
            '<a onclick="xss()">click</a>',
            "data:text/html,<script>alert(1)</script>",
        ],
        ids=lambda p: p[:40],
    )
    def test_detects_xss(self, payload: str) -> None:
        with pytest.raises(ValueError, match="potential XSS"):
            validate_no_script(payload)

    @pytest.mark.parametrize(
        "safe_input",
        [
            "hello world",
            "price > 100",
            "a < b and c > d",
            "user@example.com",
            "正常中文输入",
            "https://example.com/page",
        ],
    )
    def test_allows_safe_input(self, safe_input: str) -> None:
        assert validate_no_script(safe_input) == safe_input

    def test_non_string_raises(self) -> None:
        with pytest.raises(ValueError, match="expected str"):
            validate_no_script(123)  # type: ignore[arg-type]


class TestGetCspHeader:
    def test_contains_required_directives(self) -> None:
        csp = get_csp_header()
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "base-uri 'self'" in csp

    def test_no_unsafe_eval(self) -> None:
        csp = get_csp_header()
        assert "unsafe-eval" not in csp

    def test_returns_string(self) -> None:
        assert isinstance(get_csp_header(), str)
