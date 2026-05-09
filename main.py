import korea_tool
from kis_query_utils import issue_access_token

token = issue_access_token()

#korea_tool.price_viewer(token, "005930")

"""korea_tool.order_stock(
    token,
    order_type="buy",
    stock_code="005930",
    quantity=1,
    price=100000
)"""

#korea_tool.order_history_check(token)

#korea_tool.unfilled_orders_check(token)

korea_tool.balance_check(token)
