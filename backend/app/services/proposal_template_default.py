"""Встроенный (дефолтный) HTML-шаблон коммерческого предложения.

Используется, если администратор не загрузил собственный шаблон через MinIO.
Поддерживает условные блоки по флагу `vat_included`.

Контекст рендеринга (одинаков для встроенного и загруженного шаблонов):
- `seller`   — реквизиты продавца (объект с полями seller_name, seller_inn, ...);
- `client`   — реквизиты покупателя (name, inn, address, contact_person, email, phone);
- `proposal` — {number, date};
- `items`    — список позиций {index, name, sku, unit, quantity, price, sum};
- `vat_included` — bool, НДС выделен из цены;
- `vat_rate` — ставка НДС (число, %);
- `totals`   — {total, vat, grand_total}.
"""

DEFAULT_PROPOSAL_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<style>
  @page { size: A4; margin: 20mm 15mm; }
  body { font-family: "DejaVu Sans", sans-serif; font-size: 11px; color: #222; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .header { display: flex; justify-content: space-between; margin-bottom: 16px; }
  .seller { font-size: 10px; color: #444; max-width: 55%; }
  .meta { text-align: right; font-size: 11px; }
  .parties { margin-bottom: 14px; }
  .parties div { margin-bottom: 2px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #999; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #f0f0f0; }
  td.num, th.num { text-align: right; white-space: nowrap; }
  tfoot td { font-weight: bold; }
  .signature { margin-top: 28px; }
</style>
</head>
<body>
  <div class="header">
    <div class="seller">
      <strong>{{ seller.seller_name or "" }}</strong><br>
      {% if seller.seller_address %}Адрес: {{ seller.seller_address }}<br>{% endif %}
      {% if seller.seller_inn %}ИНН/КПП: {{ seller.seller_inn }}{% if seller.seller_kpp %} / {{ seller.seller_kpp }}{% endif %}<br>{% endif %}
      {% if seller.seller_phone %}Тел.: {{ seller.seller_phone }}{% if seller.seller_email %}, {{ seller.seller_email }}{% endif %}<br>{% endif %}
    </div>
    <div class="meta">
      <h1>Коммерческое предложение</h1>
      <div>№ {{ proposal.number }} от {{ proposal.date }}</div>
    </div>
  </div>

  <div class="parties">
    <div><strong>Покупатель:</strong> {{ client.name }}</div>
    <div>ИНН: {{ client.inn }}</div>
    <div>Адрес: {{ client.address }}</div>
    <div>Контактное лицо: {{ client.contact_person }}{% if client.phone %}, тел.: {{ client.phone }}{% endif %}</div>
    <div>Email: {{ client.email }}</div>
  </div>

  <table>
    <thead>
      <tr>
        <th class="num">№</th>
        <th>Наименование</th>
        <th>Артикул</th>
        <th>Ед.</th>
        <th class="num">Кол-во</th>
        <th class="num">Цена</th>
        <th class="num">Сумма</th>
      </tr>
    </thead>
    <tbody>
      {% for item in items %}
      <tr>
        <td class="num">{{ item.index }}</td>
        <td>{{ item.name }}</td>
        <td>{{ item.sku }}</td>
        <td>{{ item.unit or "" }}</td>
        <td class="num">{{ item.quantity }}</td>
        <td class="num">{{ item.price }}</td>
        <td class="num">{{ item.sum }}</td>
      </tr>
      {% endfor %}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="6">Итого</td>
        <td class="num">{{ totals.total }}</td>
      </tr>
      {% if vat_included %}
      <tr>
        <td colspan="6">В том числе НДС {{ vat_rate }}%</td>
        <td class="num">{{ totals.vat }}</td>
      </tr>
      {% else %}
      <tr>
        <td colspan="6">Без НДС</td>
        <td class="num">{{ totals.total }}</td>
      </tr>
      {% endif %}
      <tr>
        <td colspan="6">Всего</td>
        <td class="num">{{ totals.grand_total }}</td>
      </tr>
    </tfoot>
  </table>

  <div class="signature">
    <div>{{ seller.signer_position or "Руководитель" }} ____________________ {{ seller.signer_name or "" }}</div>
  </div>
</body>
</html>
"""
