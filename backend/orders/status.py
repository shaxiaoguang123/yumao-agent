"""Status labels observed in the official order detail page."""

ORDER_STATUSES = {
    "1": "待使用", "2": "取消预约", "3": "违约", "4": "完成",
    "5": "待支付", "6": "待评价", "7": "取消预约审批中", "8": "使用中",
    "9": "失效", "10": "包场待审批", "11": "包场审批不通过",
    "12": "挂账待审批", "13": "挂账审批不通过", "14": "等待管理员审批",
    "15": "预约审批未通过",
}
CONFIRMED_ORDER_STATUSES = frozenset({"1", "4", "6", "8"})


def order_status(value: object) -> str:
    code = str(value) if type(value) in {str, int} else ""
    return code if code in ORDER_STATUSES else ""


def order_is_confirmed(value: object) -> bool:
    # A pending order's detail can contain paytime even when no payment occurred.
    return type(value) is dict and order_status(value.get("status")) in CONFIRMED_ORDER_STATUSES
