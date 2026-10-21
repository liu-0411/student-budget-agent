import sqlite3
import json
import re
from datetime import datetime

# ---------------------- SQLite 账本初始化 ----------------------
DB_PATH = "book.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 消费流水表
    cur.execute('''
                CREATE TABLE IF NOT EXISTS expense
                (
                    id
                    INTEGER
                    PRIMARY
                    KEY
                    AUTOINCREMENT,
                    amount
                    REAL,
                    category
                    TEXT,
                    note
                    TEXT,
                    create_time
                    TIMESTAMP
                    DEFAULT
                    CURRENT_TIMESTAMP
                )
                ''')
    # 预算表
    cur.execute('''
                CREATE TABLE IF NOT EXISTS budget
                (
                    id
                    INTEGER
                    PRIMARY
                    KEY
                    AUTOINCREMENT,
                    month
                    TEXT
                    UNIQUE,
                    total_budget
                    REAL
                )
                ''')
    # 默认插入一条10月预算，方便测试
    cur.execute("INSERT OR IGNORE INTO budget(month, total_budget) VALUES ('2026-10', 1500.0)")
    conn.commit()
    conn.close()


# ---------------------- 工具函数（真实操作数据库） ----------------------
def add_expense(amount: float, category: str, note: str):
    """记录一笔消费"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO expense(amount, category, note) VALUES (?, ?, ?)",
                (amount, category, note))
    conn.commit()
    conn.close()
    return json.dumps({
        "status": "ok",
        "msg": f"已记账：{amount}元，类别：{category}，备注：{note}"
    }, ensure_ascii=False)


def query_budget(month: str):
    """查询某月预算与已消费总和"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_budget FROM budget WHERE month=?", (month,))
    row = cur.fetchone()
    budget = row[0] if row else 0.0

    cur.execute('''
                SELECT SUM(amount)
                FROM expense
                WHERE strftime('%Y-%m', create_time) = ?
                ''', (month,))
    spent_row = cur.fetchone()
    spent = spent_row[0] if spent_row[0] else 0.0
    conn.close()
    remain = budget - spent
    return json.dumps({
        "month": month,
        "budget": budget,
        "spent": spent,
        "remain": remain
    }, ensure_ascii=False)


def analyze_spending(month: str):
    """按分类统计某月消费"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
                SELECT category, SUM(amount)
                FROM expense
                WHERE strftime('%Y-%m', create_time) = ?
                GROUP BY category
                ''', (month,))
    items = cur.fetchall()
    conn.close()
    data = [{"category": c, "amount": a} for c, a in items]
    return json.dumps({
        "month": month,
        "category_stat": data
    }, ensure_ascii=False)


def generate_report(month: str):
    """生成完整月度消费报告"""
    budget_info = json.loads(query_budget(month))
    cat_info = json.loads(analyze_spending(month))
    report = {
        "month": month,
        "budget_info": budget_info,
        "category_stat": cat_info["category_stat"]
    }
    return json.dumps(report, ensure_ascii=False)


# 工具映射
tool_map = {
    "add_expense": add_expense,
    "query_budget": query_budget,
    "analyze_spending": analyze_spending,
    "generate_report": generate_report
}


# ---------------------- 简易意图识别（替代大模型，本地运行） ----------------------
def parse_user_input(text):
    """从用户输入中提取金额、分类、备注、月份等信息"""
    result = {
        "intent": "unknown",
        "amount": None,
        "category": None,
        "note": "",
        "month": "2026-10"  # 默认当前月
    }

    # 提取金额
    amount_match = re.search(r'(\d+(\.\d+)?)[块元]', text)
    if amount_match:
        result["amount"] = float(amount_match.group(1))

    # 识别分类
    categories = ["餐饮", "购物", "出行", "学习", "娱乐"]
    for cat in categories:
        if cat in text:
            result["category"] = cat
            break

    # 提取备注
    if "备注" in text:
        note_part = text.split("备注")[-1].strip()
        result["note"] = note_part
    elif result["amount"] and result["category"]:
        # 简单提取备注
        result["note"] = text.strip()

    # 识别意图
    if "预算" in text or "还剩" in text or "花了多少" in text:
        result["intent"] = "query_budget"
    elif "报告" in text or "月报" in text or "总结" in text:
        result["intent"] = "generate_report"
    elif "统计" in text or "分类" in text or "花在哪" in text:
        result["intent"] = "analyze_spending"
    elif result["amount"] is not None or "记账" in text or "花了" in text:
        result["intent"] = "add_expense"

    # 提取月份
    month_match = re.search(r'(\d{4})[-年](\d{1,2})月?', text)
    if month_match:
        y = month_match.group(1)
        m = month_match.group(2).zfill(2)
        result["month"] = f"{y}-{m}"

    return result


# ---------------------- Agent 主逻辑（保留完整 Trace 日志） ----------------------
SYSTEM_PROMPT = """
你是大学生记账预算管理Agent。
能力：记录消费、查询月度预算、分类统计开销、生成月度消费报告。
规则：
1. 记账缺少金额/分类时，主动反问用户补齐
2. 严格只使用提供的4个工具
3. 禁止真实资金操作，仅做本地账本记录
"""


def agent_chat(user_input: str):
    print("\n" + "=" * 50)
    print("===== Agent Trace 日志 =====")

    parsed = parse_user_input(user_input)
    intent = parsed["intent"]

    # 场景1：记账意图
    if intent == "add_expense":
        # 参数缺失则追问
        if parsed["amount"] is None:
            print(f"[Thought] 用户要记账，但缺少金额信息，需要追问")
            print(f"[FinalAnswer] 请问这笔消费是多少钱呢？")
            print("=" * 50 + "\n")
            return "请问这笔消费是多少钱呢？"

        if parsed["category"] is None:
            print(f"[Thought] 用户要记账，但缺少分类信息，根据规则必须追问")
            print(f"[FinalAnswer] 请问这笔消费属于哪个类别？可选：餐饮、购物、出行、学习、娱乐")
            print("=" * 50 + "\n")
            return "请问这笔消费属于哪个类别？可选：餐饮、购物、出行、学习、娱乐"

        # 参数完整，调用工具
        print(f"[Thought] 用户需要记录一笔消费，信息完整，调用 add_expense 工具")
        print(
            f"[Action] add_expense 参数：amount={parsed['amount']}, category={parsed['category']}, note={parsed['note']}")

        obs = add_expense(parsed["amount"], parsed["category"], parsed["note"])
        print(f"[Observation] {obs}")

        print(f"[Thought] 记账成功，整理结果回复用户")
        result = json.loads(obs)
        final_answer = f"✅ {result['msg']}"
        print(f"[FinalAnswer] {final_answer}")
        print("=" * 50 + "\n")
        return final_answer

    # 场景2：查询预算
    elif intent == "query_budget":
        print(f"[Thought] 用户需要查询预算，调用 query_budget 工具")
        print(f"[Action] query_budget 参数：month={parsed['month']}")

        obs = query_budget(parsed["month"])
        print(f"[Observation] {obs}")

        data = json.loads(obs)
        print(f"[Thought] 查询完成，整理结果回复用户")
        final_answer = (f"📊 {data['month']} 预算情况：\n"
                        f"总预算：{data['budget']} 元\n"
                        f"已消费：{data['spent']} 元\n"
                        f"剩余：{data['remain']} 元")
        print(f"[FinalAnswer] {final_answer}")
        print("=" * 50 + "\n")
        return final_answer

    # 场景3：分类统计
    elif intent == "analyze_spending":
        print(f"[Thought] 用户需要分类统计消费，调用 analyze_spending 工具")
        print(f"[Action] analyze_spending 参数：month={parsed['month']}")

        obs = analyze_spending(parsed["month"])
        print(f"[Observation] {obs}")

        data = json.loads(obs)
        print(f"[Thought] 统计完成，整理结果回复用户")
        lines = [f"📈 {data['month']} 分类消费统计："]
        for item in data["category_stat"]:
            lines.append(f"• {item['category']}：{item['amount']} 元")
        final_answer = "\n".join(lines)
        print(f"[FinalAnswer] {final_answer}")
        print("=" * 50 + "\n")
        return final_answer

    # 场景4：生成月度报告
    elif intent == "generate_report":
        print(f"[Thought] 用户需要完整月度报告，调用 generate_report 工具")
        print(f"[Action] generate_report 参数：month={parsed['month']}")

        obs = generate_report(parsed["month"])
        print(f"[Observation] {obs}")

        report = json.loads(obs)
        bi = report["budget_info"]
        print(f"[Thought] 报告生成完成，整理成自然语言回复")

        lines = [f"📋 {report['month']} 月度消费报告",
                 f"────────────────",
                 f"总预算：{bi['budget']} 元",
                 f"已支出：{bi['spent']} 元",
                 f"剩余：{bi['remain']} 元",
                 f"────────────────",
                 f"分类明细："]
        for item in report["category_stat"]:
            lines.append(f"  • {item['category']}：{item['amount']} 元")

        final_answer = "\n".join(lines)
        print(f"[FinalAnswer] {final_answer}")
        print("=" * 50 + "\n")
        return final_answer

    # 未知意图
    else:
        print(f"[Thought] 无法识别用户意图，引导用户使用已知功能")
        final_answer = "我可以帮你记账、查预算、统计消费、生成月报。试试说：“今天吃饭花了20元，餐饮”"
        print(f"[FinalAnswer] {final_answer}")
        print("=" * 50 + "\n")
        return final_answer


# ---------------------- 主程序入口 ----------------------
if __name__ == "__main__":
    init_db()
    print("=" * 40)
    print("==== 大学生记账 Agent 启动 ====")
    print("=" * 40)
    print("示例输入：")
    print("  1. 今天吃饭花了22元，餐饮，备注食堂三楼")
    print("  2. 帮我查2026-10月预算")
    print("  3. 生成2026-10月消费报告")
    print("输入 exit 退出\n")

    while True:
        user_text = input("请输入你的请求：")
        if user_text.strip() == "exit":
            print("程序已退出")
            break
        ans = agent_chat(user_text)
        print(f"\nAgent回复：\n{ans}\n")
