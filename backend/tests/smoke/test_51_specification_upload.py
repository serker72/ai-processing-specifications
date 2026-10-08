"""
Smoke-тест: Задача 5.1 — Приём файлов клиентов.

Запуск:
    docker compose exec -T backend python3 /app/tests/smoke/test_51_specification_upload.py
"""
import json, urllib.request, io, zipfile, time
from urllib.error import HTTPError

BASE = "http://backend:8000/api/v1"
EMAIL = "smoke@example.com"
PASSWORD = "smoke_test_pass"
FINGERPRINT = "smoke-fp-001"


def login() -> str:
    """Войти как менеджер, вернуть access_token."""
    data = json.dumps({"email": EMAIL, "password": PASSWORD, "fingerprint": FINGERPRINT}).encode()
    req = urllib.request.Request(f"{BASE}/auth/login", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        cookies = [v for k, v in resp.getheaders() if k.lower() == "set-cookie"]
        return next(c.split(";")[0].split("=", 1)[1] for c in cookies if c.startswith("access_token="))


def make_xlsx() -> bytes:
    """Минимальный xlsx-файл (zip с xml)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '</Types>')
        zf.writestr("_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
        zf.writestr("xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '</Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>'
            '<row r="1"><c r="A1" t="str"><v>Наименование</v></c><c r="B1" t="str"><v>Количество</v></c></row>'
            '<row r="2"><c r="A2" t="str"><v>Widget A</v></c><c r="B2" t="n"><v>10</v></c></row>'
            '<row r="3"><c r="A3" t="str"><v>Widget B</v></c><c r="B3" t="n"><v>5</v></c></row>'
            '</sheetData></worksheet>')
    return buf.getvalue()


def upload_spec(token: str, client_id: str) -> str:
    """Загрузить спецификацию, вернуть upload_id."""
    boundary = "bnd123"
    xlsx = make_xlsx()
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="spec.xlsx"\r\n'
        f'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'.encode() +
        xlsx +
        f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="client_id"\r\n\r\n{client_id}'.encode() +
        f'\r\n--{boundary}--\r\n'.encode()
    )
    req = urllib.request.Request(f"{BASE}/manager/specifications", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Cookie": f"access_token={token}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())["upload_id"]


def check_status(token: str, upload_id: str, max_wait: int = 30) -> str:
    """Ждать завершения обработки, вернуть финальный статус."""
    for _ in range(max_wait // 2):
        time.sleep(2)
        req = urllib.request.Request(f"{BASE}/manager/specifications/{upload_id}",
                                     headers={"Cookie": f"access_token={token}"}, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = json.loads(resp.read().decode())["status"]
            if status in ("completed", "failed"):
                return status
    return "timeout"


def check_sse(token: str, upload_id: str) -> list[dict]:
    """Прочитать SSE-события, вернуть список."""
    req = urllib.request.Request(f"{BASE}/manager/specifications/{upload_id}/stream",
                                 headers={"Cookie": f"access_token={token}"}, method="GET")
    events = []
    with urllib.request.urlopen(req, timeout=5) as resp:
        for line in resp:
            decoded = line.decode().strip()
            if decoded.startswith("data:"):
                try:
                    events.append(json.loads(decoded[5:]))
                except json.JSONDecodeError:
                    pass
            if len(events) >= 5:
                break
    return events


def main() -> None:
    print("=" * 50)
    print("Smoke-тест: Задача 5.1 — Приём файлов клиентов")
    print("=" * 50)

    # 1. Login
    token = login()
    print(f"[1] Login OK (token len={len(token)})")

    # 2. Create client
    client_data = json.dumps({"name": "Smoke Test Client", "inn": "1234567890",
                               "address": "Test str 1", "contact_person": "Ivanov",
                               "email": "smoke@test.ru"}).encode()
    req = urllib.request.Request(f"{BASE}/manager/clients", data=client_data,
        headers={"Content-Type": "application/json", "Cookie": f"access_token={token}"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        client_id = json.loads(resp.read().decode())["id"]
    print(f"[2] Client created: {client_id}")

    # 3. Upload spec
    upload_id = upload_spec(token, client_id)
    print(f"[3] Upload spec: 202, upload_id={upload_id}")

    # 4. Wait for processing
    status = check_status(token, upload_id)
    print(f"[4] Final status: {status}")

    # 5. Check rows
    req = urllib.request.Request(f"{BASE}/manager/specifications/{upload_id}/rows",
                                 headers={"Cookie": f"access_token={token}"}, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
        rows = data.get("rows", [])
    print(f"[5] Rows: total={data.get('total', 0)}")
    for row in rows:
        print(f"    {row['raw_name']} → {row.get('catalog_item_name', 'N/A')} | {row.get('match_type', 'N/A')} | {row.get('status', 'N/A')}")

    # 6. Check SSE
    events = check_sse(token, upload_id)
    print(f"[6] SSE events: {len(events)}")
    for e in events:
        print(f"    seq={e.get('seq')} status={e.get('status')} msg={e.get('message', '')}")

    # Summary
    print("\n" + "=" * 50)
    ok = status == "completed" and len(rows) > 0
    print("RESULT:", "PASS ✓" if ok else "FAIL ✗")
    print("=" * 50)


if __name__ == "__main__":
    main()
