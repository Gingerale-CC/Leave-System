import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import date, datetime
import io

st.set_page_config(page_title="员工请假系统", layout="wide")

# ---------------------------------------------------
# 连接 Supabase（密钥在 Streamlit 的 Secrets 里配置，不写在代码里）
# ---------------------------------------------------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

LEAVE_TYPES = ["年假", "事假", "病假", "调休假"]
CURRENT_YEAR = datetime.now().year


# =====================================================
# 工具函数
# =====================================================
def get_user_by_username(username):
    res = supabase.table("users").select("*").eq("username", username).execute()
    return res.data[0] if res.data else None


def get_all_users():
    res = supabase.table("users").select("*").order("id").execute()
    return res.data


def get_balances(user_id, year):
    res = (
        supabase.table("leave_balances")
        .select("*")
        .eq("user_id", user_id)
        .eq("year", year)
        .execute()
    )
    return res.data


def upsert_balance(user_id, year, leave_type, total_days):
    existing = (
        supabase.table("leave_balances")
        .select("*")
        .eq("user_id", user_id)
        .eq("year", year)
        .eq("leave_type", leave_type)
        .execute()
    ).data
    if existing:
        supabase.table("leave_balances").update({"total_days": total_days}).eq(
            "id", existing[0]["id"]
        ).execute()
    else:
        supabase.table("leave_balances").insert(
            {
                "user_id": user_id,
                "year": year,
                "leave_type": leave_type,
                "total_days": total_days,
                "used_days": 0,
            }
        ).execute()


def adjust_used_days(user_id, year, leave_type, delta_days):
    """审批通过/驳回时，调整已用天数（只有当该假期类型已经被管理员设置过额度记录时才会记录扣减）"""
    existing = (
        supabase.table("leave_balances")
        .select("*")
        .eq("user_id", user_id)
        .eq("year", year)
        .eq("leave_type", leave_type)
        .execute()
    ).data
    if existing:
        new_used = float(existing[0]["used_days"]) + delta_days
        if new_used < 0:
            new_used = 0
        supabase.table("leave_balances").update({"used_days": new_used}).eq(
            "id", existing[0]["id"]
        ).execute()


def users_dict():
    users = get_all_users()
    return {u["id"]: u for u in users}


# =====================================================
# 登录页
# =====================================================
def login_page():
    st.title("📋 员工请假系统")
    st.subheader("登录")
    with st.form("login_form"):
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录")
        if submitted:
            user = get_user_by_username(username.strip())
            if user and user["password"] == password:
                st.session_state["user"] = user
                st.rerun()
            else:
                st.error("用户名或密码错误，请重试")


def logout_sidebar(user):
    st.sidebar.markdown(f"### 👤 {user['name']}")
    role_label = {"admin": "管理员", "manager": "经理", "employee": "员工"}[user["role"]]
    st.sidebar.caption(f"角色：{role_label}")
    if st.sidebar.button("退出登录"):
        del st.session_state["user"]
        st.rerun()


# =====================================================
# 员工视图
# =====================================================
def employee_view(user):
    st.header(f"欢迎，{user['name']}")
    tab1, tab2, tab3 = st.tabs(["📊 我的假期余额", "📝 提交请假申请", "📄 我的申请记录"])

    with tab1:
        balances = get_balances(user["id"], CURRENT_YEAR)
        if balances:
            rows = []
            for b in balances:
                remaining = float(b["total_days"]) - float(b["used_days"])
                rows.append(
                    {
                        "假期类型": b["leave_type"],
                        "年度总额度(天)": b["total_days"],
                        "已使用(天)": b["used_days"],
                        "剩余(天)": remaining,
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info(f"管理员还没有为你设置 {CURRENT_YEAR} 年的假期额度。事假/病假不受额度限制，仍可正常申请。")

    with tab2:
        with st.form("apply_leave"):
            leave_type = st.selectbox("假期类型", LEAVE_TYPES)
            col1, col2 = st.columns(2)
            start_d = col1.date_input("开始日期", value=date.today())
            end_d = col2.date_input("结束日期", value=date.today())
            reason = st.text_area("请假事由")
            submitted = st.form_submit_button("提交申请")
            if submitted:
                if end_d < start_d:
                    st.error("结束日期不能早于开始日期")
                else:
                    days = (end_d - start_d).days + 1
                    supabase.table("leave_requests").insert(
                        {
                            "user_id": user["id"],
                            "leave_type": leave_type,
                            "start_date": start_d.isoformat(),
                            "end_date": end_d.isoformat(),
                            "days": days,
                            "reason": reason,
                            "status": "待审批",
                        }
                    ).execute()
                    st.success(f"申请已提交，共 {days} 天，等待经理审批")
                    st.rerun()

    with tab3:
        res = (
            supabase.table("leave_requests")
            .select("*")
            .eq("user_id", user["id"])
            .order("submitted_at", desc=True)
            .execute()
        )
        if res.data:
            df = pd.DataFrame(res.data)[
                ["leave_type", "start_date", "end_date", "days", "status", "reason", "approver_comment"]
            ]
            df.columns = ["假期类型", "开始日期", "结束日期", "天数", "状态", "事由", "审批备注"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无申请记录")


# =====================================================
# 经理视图
# =====================================================
def manager_view(user):
    st.header(f"欢迎，{user['name']}（经理）")
    all_users = users_dict()
    my_team_ids = [u["id"] for u in all_users.values() if u["manager_id"] == user["id"]]

    tab1, tab2 = st.tabs(["🕒 待审批申请", "📚 审批历史"])

    with tab1:
        if not my_team_ids:
            st.info("你名下暂无员工")
        else:
            res = (
                supabase.table("leave_requests")
                .select("*")
                .in_("user_id", my_team_ids)
                .eq("status", "待审批")
                .order("submitted_at")
                .execute()
            )
            if not res.data:
                st.info("暂无待审批的申请")
            for r in res.data:
                emp = all_users.get(r["user_id"], {})
                with st.container(border=True):
                    st.markdown(
                        f"**{emp.get('name','未知')}** 申请 **{r['leave_type']}**："
                        f"{r['start_date']} ~ {r['end_date']}（共 {r['days']} 天）"
                    )
                    st.caption(f"事由：{r['reason'] or '（未填写）'}")
                    comment = st.text_input("审批备注（可选）", key=f"comment_{r['id']}")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ 通过", key=f"approve_{r['id']}"):
                        supabase.table("leave_requests").update(
                            {
                                "status": "已通过",
                                "approver_comment": comment,
                                "approved_at": datetime.now().isoformat(),
                            }
                        ).eq("id", r["id"]).execute()
                        start_year = int(r["start_date"][:4])
                        adjust_used_days(r["user_id"], start_year, r["leave_type"], float(r["days"]))
                        st.rerun()
                    if c2.button("❌ 驳回", key=f"reject_{r['id']}"):
                        supabase.table("leave_requests").update(
                            {
                                "status": "已驳回",
                                "approver_comment": comment,
                                "approved_at": datetime.now().isoformat(),
                            }
                        ).eq("id", r["id"]).execute()
                        st.rerun()

    with tab2:
        if my_team_ids:
            res = (
                supabase.table("leave_requests")
                .select("*")
                .in_("user_id", my_team_ids)
                .neq("status", "待审批")
                .order("approved_at", desc=True)
                .execute()
            )
            if res.data:
                df = pd.DataFrame(res.data)
                df["姓名"] = df["user_id"].map(lambda uid: all_users.get(uid, {}).get("name", ""))
                df = df[["姓名", "leave_type", "start_date", "end_date", "days", "status", "approver_comment"]]
                df.columns = ["姓名", "假期类型", "开始日期", "结束日期", "天数", "状态", "审批备注"]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("暂无审批历史")


# =====================================================
# 管理员视图
# =====================================================
def admin_view(user):
    st.header(f"欢迎，{user['name']}（管理员）")
    tab1, tab2, tab3, tab4 = st.tabs(
        ["👥 员工账号管理", "📅 假期额度设置", "📤 报表导出", "📋 全部申请记录"]
    )

    all_users = get_all_users()

    # ---------------- 员工账号管理 ----------------
    with tab1:
        st.subheader("现有账号")
        if all_users:
            df = pd.DataFrame(all_users)
            role_map = {"admin": "管理员", "manager": "经理", "employee": "员工"}
            df["role_label"] = df["role"].map(role_map)
            id_name_map = {u["id"]: u["name"] for u in all_users}
            df["manager_name"] = df["manager_id"].map(lambda x: id_name_map.get(x, ""))
            show_df = df[["username", "name", "role_label", "manager_name", "department"]]
            show_df.columns = ["用户名", "姓名", "角色", "所属经理", "部门"]
            st.dataframe(show_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("新增账号")
        manager_options = {u["name"]: u["id"] for u in all_users if u["role"] in ("manager", "admin")}
        with st.form("add_user"):
            new_username = st.text_input("用户名（员工登录用，如 zhangsan）")
            new_password = st.text_input("初始密码")
            new_name = st.text_input("姓名")
            new_role = st.selectbox("角色", ["employee", "manager", "admin"], format_func=lambda x: {"employee": "员工", "manager": "经理", "admin": "管理员"}[x])
            new_manager = st.selectbox("所属经理（员工必选，经理/管理员可不选）", ["（无）"] + list(manager_options.keys()))
            new_dept = st.text_input("部门（可选）")
            submitted = st.form_submit_button("创建账号")
            if submitted:
                if not new_username or not new_password or not new_name:
                    st.error("用户名、密码、姓名为必填项")
                else:
                    manager_id = manager_options.get(new_manager) if new_manager != "（无）" else None
                    supabase.table("users").insert(
                        {
                            "username": new_username.strip(),
                            "password": new_password,
                            "name": new_name,
                            "role": new_role,
                            "manager_id": manager_id,
                            "department": new_dept,
                        }
                    ).execute()
                    st.success(f"账号 {new_username} 创建成功")
                    st.rerun()

        st.divider()
        st.subheader("重置某个员工的密码")
        if all_users:
            username_options = {u["name"] + f"（{u['username']}）": u["id"] for u in all_users}
            with st.form("reset_pw"):
                target = st.selectbox("选择员工", list(username_options.keys()))
                new_pw = st.text_input("新密码")
                reset_submit = st.form_submit_button("重置密码")
                if reset_submit and new_pw:
                    supabase.table("users").update({"password": new_pw}).eq(
                        "id", username_options[target]
                    ).execute()
                    st.success("密码已重置")

    # ---------------- 假期额度设置 ----------------
    with tab2:
        st.subheader("设置员工年度假期额度")
        year_sel = st.number_input("年度", min_value=2020, max_value=2100, value=CURRENT_YEAR, step=1)
        employee_options = {u["name"] + f"（{u['username']}）": u["id"] for u in all_users if u["role"] != "admin"}
        if employee_options:
            with st.form("set_balance"):
                emp_choice = st.selectbox("选择员工", list(employee_options.keys()))
                lt = st.selectbox("假期类型", LEAVE_TYPES)
                total = st.number_input("总额度（天）", min_value=0.0, step=0.5)
                bal_submit = st.form_submit_button("保存额度")
                if bal_submit:
                    upsert_balance(employee_options[emp_choice], int(year_sel), lt, total)
                    st.success("额度已保存")

        st.divider()
        st.subheader(f"{year_sel} 年 全员假期额度总览")
        res = supabase.table("leave_balances").select("*").eq("year", int(year_sel)).execute()
        if res.data:
            id_name_map = {u["id"]: u["name"] for u in all_users}
            df = pd.DataFrame(res.data)
            df["姓名"] = df["user_id"].map(id_name_map)
            df["剩余"] = df["total_days"].astype(float) - df["used_days"].astype(float)
            df = df[["姓名", "leave_type", "total_days", "used_days", "剩余"]]
            df.columns = ["姓名", "假期类型", "总额度", "已用", "剩余"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("该年度还没有设置任何额度")

    # ---------------- 报表导出 ----------------
    with tab3:
        st.subheader("按月导出假期记录报表")
        col1, col2 = st.columns(2)
        y = col1.number_input("年", min_value=2020, max_value=2100, value=CURRENT_YEAR, step=1, key="exp_y")
        m = col2.number_input("月", min_value=1, max_value=12, value=datetime.now().month, step=1, key="exp_m")
        if st.button("生成报表"):
            res = supabase.table("leave_requests").select("*").execute()
            if res.data:
                id_name_map = {u["id"]: u["name"] for u in all_users}
                df = pd.DataFrame(res.data)
                df["start_date_dt"] = pd.to_datetime(df["start_date"])
                mask = (df["start_date_dt"].dt.year == int(y)) & (df["start_date_dt"].dt.month == int(m))
                month_df = df[mask].copy()
                month_df["姓名"] = month_df["user_id"].map(id_name_map)
                month_df = month_df[
                    ["姓名", "leave_type", "start_date", "end_date", "days", "status", "reason", "approver_comment", "submitted_at"]
                ]
                month_df.columns = ["姓名", "假期类型", "开始日期", "结束日期", "天数", "状态", "事由", "审批备注", "提交时间"]
                st.dataframe(month_df, use_container_width=True, hide_index=True)

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    month_df.to_excel(writer, index=False, sheet_name="请假记录")
                st.download_button(
                    "⬇️ 下载 Excel 报表",
                    data=buffer.getvalue(),
                    file_name=f"请假记录_{y}年{m}月.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            else:
                st.info("暂无数据")

    # ---------------- 全部申请记录 ----------------
    with tab4:
        res = supabase.table("leave_requests").select("*").order("submitted_at", desc=True).execute()
        if res.data:
            id_name_map = {u["id"]: u["name"] for u in all_users}
            df = pd.DataFrame(res.data)
            df["姓名"] = df["user_id"].map(id_name_map)
            df = df[["姓名", "leave_type", "start_date", "end_date", "days", "status", "reason", "approver_comment"]]
            df.columns = ["姓名", "假期类型", "开始日期", "结束日期", "天数", "状态", "事由", "审批备注"]
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无记录")


# =====================================================
# 主程序入口
# =====================================================
if "user" not in st.session_state:
    login_page()
else:
    current_user = get_user_by_username(st.session_state["user"]["username"])  # 每次拉取最新信息
    st.session_state["user"] = current_user
    logout_sidebar(current_user)

    if current_user["role"] == "employee":
        employee_view(current_user)
    elif current_user["role"] == "manager":
        manager_view(current_user)
    elif current_user["role"] == "admin":
        admin_view(current_user)
