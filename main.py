import os
import json
import sqlite3
from dotenv import load_dotenv
from openai import OpenAI

# 加载环境变量
load_dotenv()
client = OpenAI(
    base_url=os.getenv("BASE_URL"),
    api_key=os.getenv("API_KEY")
)
MODEL = os.getenv("MODEL")

# ---------------------- SQLite 账本初始化 ----------------------
DB_PATH = "book.db"
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # 消费流水表
    cur.execute('''
    CREATE TABLE IF NOT EXISTS expense(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL,
        category TEXT,
        note TEXT,
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    # 预算表，简单只存单月总预算
    cur.execute('''
    CREATE TABLE IF NOT EXISTS budget(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month TEXT UNIQUE,
        total_budget REAL
    )
    ''')
    conn.commit()
    conn.close()

# ---------------------- 工具函数（给Agent调用） ----------------------
def add_expense(amount:float, category:str, note:str):
    """
    add_expense：记录一笔消费
    参数: amount 金额; category分类(餐饮/购物/出行/学习/娱乐); note备注
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO expense(amount,category,note) VALUES (?,?,?)",(amount,category,note))
    conn.commit()
    conn.close()
    return json.dumps({"status":"ok","msg":f"已记账：{amount}元，类别：{category}，备注：{note}"})

def query_budget(month:str):
    """
    query_budget 查询某月预算与当月已消费总和
    :param month: 例如 "2026‑10"
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT total_budget FROM budget WHERE month=?",(month,))
    row = cur.fetchone()
    budget = row[0] if row else 0.0

    cur.execute('''
    SELECT SUM(amount) FROM expense WHERE strftime('%Y‑%m',create_time) = ?
    ''',(month,))
    spent_row = cur.fetchone()
    spent = spent_row[0] if spent_row[0] else 0.0
    conn.close()
    remain = budget - spent
    return json.dumps({"month":month,"budget":budget,"spent":spent,"remain":remain})

def analyze_spending(month:str):
    """analyze_spending：按分类统计某月各个类别的消费金额"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
    SELECT category,SUM(amount) FROM expense
    WHERE strftime('%Y‑%m',create_time)=?
    GROUP BY category
    ''',(month,))
    items = cur.fetchall()
    conn.close()
    data = [{"category":c,"amount":a} for c,a in items]
    return json.dumps({"month":month,"category_stat":data})

def generate_report(month:str):
    """generate_report 生成月度消费报告，整合预算和分类统计"""
    budget_info = json.loads(query_budget(month))
    cat_info = json.loads(analyze_spending(month))
    report = {
        "month":month,
        "budget_info":budget_info,
        "category_stat":cat_info["category_stat"]
    }
    return json.dumps(report,ensure_ascii=False)

# 工具描述，供Function Calling
tools = [
    {
        "type":"function",
        "function":{
            "name":"add_expense",
            "description":"记录一笔消费，必须传入amount金额、category消费分类、note备注",
            "parameters":{
                "type":"object",
                "required":["amount","category","note"],
                "properties":{
                    "amount":{"type":"number","description":"消费金额，正数"},
                    "category":{"type":"string","description":"只能选：餐饮、购物、出行、学习、娱乐"},
                    "note":{"type":"string","description":"消费简单备注"}
                }
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"query_budget",
            "description":"查询指定月份预算、已花金额、剩余预算，参数month格式'YYYY‑MM'",
            "parameters":{
                "type":"object",
                "required":["month"],
                "properties":{"month":{"type":"string","description":"年月，例如2026‑10"}}
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"analyze_spending",
            "description":"统计某月各个消费类别的开销，month格式YYYY‑MM",
            "parameters":{
                "type":"object",
                "required":["month"],
                "properties":{"month":{"type":"string"}}
            }
        }
    },
    {
        "type":"function",
        "function":{
            "name":"generate_report",
            "description":"生成完整月度消费报告，包含预算+分类统计，month格式YYYY‑MM",
            "parameters":{
                "type":"object",
                "required":["month"],
                "properties":{"month":{"type":"string"}}
            }
        }
    }
]

tool_map = {
    "add_expense": add_expense,
    "query_budget": query_budget,
    "analyze_spending": analyze_spending,
    "generate_report": generate_report
}

SYSTEM_PROMPT = """
你是大学生记账预算管理Agent。
你的能力：记录消费、查询月度预算、分类统计开销、生成月度消费报告。
规则：
1. 用户记账的时候，如果缺少金额 / 分类，不要调用工具，主动反问用户补齐信息。
2. 严格只使用提供的4个工具，不要编造不存在函数。
3. 禁止做真实转账、充值操作，只做本地账本记录。
4. 思考过程内部完成，只给用户简洁易懂中文回答。
5. 最多连续调用工具5轮，超过直接终止任务，提示用户任务复杂。
"""

def agent_chat(user_input:str):
    messages = [
        {"role":"system","content":SYSTEM_PROMPT},
        {"role":"user","content":user_input}
    ]
    max_loop = 5
    loop = 0
    print("\n===== Agent Trace日志（复制到作业报告） =====")
    while loop < max_loop:
        loop +=1
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            print(f"[Thought] 直接输出回答，无需工具调用")
            print(f"[FinalAnswer]: {msg.content}")
            return msg.content

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            print(f"[Thought] 需要调用工具 {fn_name}")
            print(f"[Action] {fn_name} 参数: {fn_args}")
            fn = tool_map[fn_name]
            obs = fn(**fn_args)
            print(f"[Observation] {obs}")
            messages.append(msg.model_dump())
            messages.append({
                "role":"tool",
                "tool_call_id":tc.id,
                "content":obs
            })
    return "已到达最大工具调用轮次，任务结束，请简化你的问题。"

if __name__ == "__main__":
    init_db()
    print("==== 大学生记账Agent启动 ====")
    print("示例输入：\n1.今天吃饭花了22块，属于餐饮\n2.帮我查2026‑10月预算\n3.生成2026‑10月报告\n输入 exit 退出\n")
    while True:
        user_text = input("请输入你的请求：")
        if user_text.strip() == "exit":
            break
        ans = agent_chat(user_text)
        print(f"\nAgent回复：{ans}\n")
