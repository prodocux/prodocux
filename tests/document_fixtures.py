"""Deterministic review fixtures. No external corpus or network required."""

import io
import zipfile
from email import policy
from email.message import EmailMessage

TYPES = {"odt": "text", "ods": "spreadsheet", "odp": "presentation"}
NAMESPACES = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)


def odf(fmt, inner, *, extra=(), declaration="", mime=None):
    kind = TYPES[fmt]
    content = (f"{declaration}<office:document-content {NAMESPACES}>"
               f"<office:body><office:{kind}>{inner}</office:{kind}></office:body>"
               "</office:document-content>")
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("mimetype", mime or f"application/vnd.oasis.opendocument.{kind}")
        archive.writestr("content.xml", content)
        for name, value in extra:
            archive.writestr(name, value, compress_type=zipfile.ZIP_DEFLATED)
    return raw.getvalue()


def cases():
    mail = EmailMessage(policy=policy.SMTP)
    mail["Subject"] = "中文 subject"
    mail["From"] = "sender@example.invalid"
    mail["To"] = "recipient@example.invalid"
    mail.set_content("mailneedle 中文", cte="base64")
    mail.add_alternative('<p>htmlmailneedle</p><img src="https://invalid.example/pixel">',
                         subtype="html")
    mail.add_attachment(b"privateattachmentneedle", maintype="text", subtype="plain",
                        filename="private.txt")
    mail.set_boundary("portable-mixed")
    mail.get_payload(0).set_boundary("portable-alternative")
    return {
        "html": ((b'<html><body><p>htmlneedle &amp; result</p><script>hiddenneedle</script>'
                 b'<p hidden>hiddenneedle</p><p style="display: none">hiddenneedle</p>'
                 b'<img src="https://invalid.example/a"></body></html>'),
                 "htmlneedle & result", ["html-text", [["html", 1], ["body", 2], ["p", 3]], 4, 1, 15]),
        "json": ('{"a/b":{"~x":[null, "jsonneedle 中文"]}}'.encode(),
                 "jsonneedle 中文", ["json-pointer", "/a~1b/~0x/1"]),
        "jsonl": (b'\xef\xbb\xbf{"key":"previous"}\r\n{"key":"jsonlneedle"}\r\n',
                  "jsonlneedle", ["jsonl-record", 2, 23, 46, "/key"]),
        "odt": (odf("odt", '<text:p>odtneedle<text:s text:c="2"/><text:a xlink:href="https://invalid.example/odf">中文</text:a>'
                    '<office:annotation><text:p>hiddenneedle</text:p></office:annotation></text:p><text:tracked-changes><text:changed-region><text:deletion><text:p>DELETEDSECRET</text:p></text:deletion></text:changed-region></text:tracked-changes>'),
                "odtneedle  中文", ["odt-paragraph-xml", 1]),
        "ods": (odf("ods", '<table:table table:name="Data"><table:table-row>'
                    '<table:table-cell table:number-columns-repeated="2" table:formula="of:=1+2">'
                    '<text:p>odsneedle 中文</text:p></table:table-cell></table:table-row></table:table>'
                    '<table:table table:name="Hidden" table:display="false"><table:table-row>'
                    '<table:table-cell><text:p>hiddenneedle</text:p></table:table-cell>'
                    '</table:table-row></table:table>'),
                "odsneedle 中文", ["ods-cell-xml", "Data", 1, 1, 1]),
        "odp": (odf("odp", '<draw:page draw:name="Slide"><draw:g><draw:frame>'
                    '<draw:text-box><text:p>odpneedle 中文</text:p></draw:text-box>'
                    '</draw:frame></draw:g><presentation:notes>'
                    '<text:p>hiddenneedle</text:p></presentation:notes></draw:page>'),
                "odpneedle 中文", ["odp-slide-text-xml", 1, 1, 1, 1, 1]),
        "eml": (mail.as_bytes(), "mailneedle 中文", ["eml-body", [1, 1], "text/plain", "base64"]),
    }
