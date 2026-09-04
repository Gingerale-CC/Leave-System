-- ===================================================
-- 员工请假系统 - 数据表建表脚本
-- 使用方法：把这整段代码复制，粘贴到 Supabase 后台的
-- "SQL Editor" 里，点击 Run 运行一次即可（只需运行一次）
-- ===================================================

-- 1. 用户表：存放员工/经理/管理员的账号信息
create table users (
    id serial primary key,
    username text unique not null,
    password text not null,
    name text not null,
    role text not null check (role in ('admin','manager','employee')),
    manager_id int references users(id),
    department text
);

-- 2. 假期余额表：存放每人每年每种假期的总额度和已用天数
create table leave_balances (
    id serial primary key,
    user_id int references users(id) not null,
    year int not null,
    leave_type text not null check (leave_type in ('年假','事假','病假','调休假')),
    total_days numeric not null default 0,
    used_days numeric not null default 0,
    unique(user_id, year, leave_type)
);

-- 3. 请假申请表：存放每一条请假记录
create table leave_requests (
    id serial primary key,
    user_id int references users(id) not null,
    leave_type text not null check (leave_type in ('年假','事假','病假','调休假')),
    start_date date not null,
    end_date date not null,
    days numeric not null,
    reason text,
    status text not null default '待审批' check (status in ('待审批','已通过','已驳回')),
    approver_comment text,
    submitted_at timestamptz default now(),
    approved_at timestamptz
);

-- ===================================================
-- 4. 插入第一个管理员账号（用户名: admin，密码: admin123）
--    建好表之后，运行到这一步就有了第一个可以登录的管理员账号
--    之后强烈建议登录系统后，去数据表里把这个初始密码改掉
-- ===================================================
insert into users (username, password, name, role)
values ('admin', 'admin123', '系统管理员', 'admin');
