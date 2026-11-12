"""The demo databases SQLAgent connects to, built from a fixed seed so every run of
``make demo`` (and every integration test) sees the same rows.

* ``shop`` on PostgreSQL: customers, products, orders and order lines over three years,
  plus a monthly revenue view.
* ``people`` on MySQL: departments, employees and leave requests.
* ``subscriptions`` on SQLite: plans, accounts and invoices of a small SaaS business.

Dates are spread up to "today", so "this year" and "last year" always have data. Each
builder also creates a login that may only read (``sqlagent_reader``): the demo
connects with it, while the integration suite also connects with the admin login to
prove the session itself is read-only.
"""

from __future__ import annotations

import datetime as dt
import random
import sqlite3
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa

READER = "sqlagent_reader"
COUNTRIES = [
    "United States",
    "Germany",
    "India",
    "United Kingdom",
    "Brazil",
    "Japan",
    "France",
    "Canada",
]
FIRST = [
    "Aarav",
    "Maya",
    "Liam",
    "Sofia",
    "Noah",
    "Ava",
    "Ethan",
    "Zara",
    "Lucas",
    "Mia",
    "Arjun",
    "Elena",
    "Omar",
    "Hana",
    "Leo",
    "Chloe",
    "Ravi",
    "Nina",
    "Kai",
    "Ines",
]
LAST = [
    "Sharma",
    "Muller",
    "Smith",
    "Silva",
    "Tanaka",
    "Dubois",
    "Patel",
    "Brown",
    "Rossi",
    "Kim",
    "Garcia",
    "Nguyen",
    "Okafor",
    "Lopez",
    "Fischer",
    "Khan",
]
CATEGORIES = {
    "Electronics": [
        "Wireless Earbuds",
        "USB-C Hub",
        "Mechanical Keyboard",
        "4K Monitor",
        "Webcam HD",
        "Portable SSD",
        "Smart Speaker",
        "Laptop Stand",
    ],
    "Home": [
        "Ceramic Mug Set",
        "Linen Throw",
        "Desk Lamp",
        "Plant Pot",
        "Wall Clock",
        "Scented Candle",
        "Storage Basket",
    ],
    "Outdoors": [
        "Trail Backpack",
        "Water Bottle",
        "Camping Lantern",
        "Hiking Socks",
        "Rain Jacket",
        "Yoga Mat",
    ],
    "Books": [
        "Data Science Handbook",
        "SQL Cookbook",
        "Design Patterns",
        "Cooking at Home",
        "Travel Atlas",
        "Mystery Novel",
    ],
    "Grocery": [
        "Single Origin Coffee",
        "Green Tea Tin",
        "Dark Chocolate",
        "Olive Oil",
        "Spice Kit",
        "Granola",
    ],
}
STATUSES = [
    ("delivered", 70),
    ("shipped", 10),
    ("processing", 6),
    ("cancelled", 8),
    ("returned", 6),
]
CHANNELS = [("web", 55), ("mobile", 35), ("store", 10)]


def _pick(rng: random.Random, weighted: Sequence[tuple[str, int]]) -> str:
    return rng.choices([w[0] for w in weighted], weights=[w[1] for w in weighted])[0]


def _day(rng: random.Random, start: dt.date, end: dt.date) -> dt.date:
    return start + dt.timedelta(days=rng.randrange(max((end - start).days, 1)))


def shop_rows(today: dt.date) -> dict[str, list[tuple[Any, ...]]]:
    rng = random.Random(14)
    start = dt.date(today.year - 2, 1, 1)
    customers = []
    for i in range(1, 401):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        customers.append(
            (
                i,
                f"{first} {last}",
                f"{first.lower()}.{last.lower()}{i}@example.com",
                rng.choice(COUNTRIES),
                _pick(rng, [("consumer", 70), ("business", 22), ("enterprise", 8)]),
                _day(rng, start - dt.timedelta(days=200), today),
            )
        )
    products = []
    pid = 0
    for category, names in CATEGORIES.items():
        for name in names:
            pid += 1
            base = {"Electronics": 90, "Home": 30, "Outdoors": 45, "Books": 25, "Grocery": 12}[
                category
            ]
            products.append(
                (pid, name, category, Decimal(str(round(base * rng.uniform(0.5, 2.6), 2))))
            )
    orders = []
    items = []
    item_id = 0
    for oid in range(1, 6001):
        cust = customers[rng.randrange(len(customers))]
        # Growth: later years have more orders (a trend worth charting).
        day = _day(rng, start, today + dt.timedelta(days=1))
        if day.year < today.year and rng.random() < 0.25 * (today.year - day.year):
            day = _day(rng, dt.date(today.year, 1, 1), today + dt.timedelta(days=1))
        total = Decimal("0")
        for _ in range(rng.randint(1, 4)):
            item_id += 1
            prod = products[rng.randrange(len(products))]
            qty = rng.randint(1, 3)
            line = (prod[3] * qty).quantize(Decimal("0.01"))
            total += line
            items.append((item_id, oid, prod[0], qty, prod[3], line))
        orders.append((oid, cust[0], _pick(rng, STATUSES), day, total, _pick(rng, CHANNELS)))
    return {"customers": customers, "products": products, "orders": orders, "order_items": items}


SHOP_DDL = [
    "DROP VIEW IF EXISTS monthly_revenue",
    "DROP TABLE IF EXISTS order_items, orders, products, customers CASCADE",
    """CREATE TABLE customers (
        id integer PRIMARY KEY, name varchar(120) NOT NULL, email varchar(200) NOT NULL UNIQUE,
        country varchar(60) NOT NULL, segment varchar(20) NOT NULL, created_at date NOT NULL)""",
    """CREATE TABLE products (
        id integer PRIMARY KEY, name varchar(120) NOT NULL, category varchar(40) NOT NULL,
        unit_price numeric(10,2) NOT NULL)""",
    """CREATE TABLE orders (
        id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES customers(id),
        status varchar(20) NOT NULL, order_date date NOT NULL,
        total_amount numeric(12,2) NOT NULL, channel varchar(20) NOT NULL)""",
    """CREATE TABLE order_items (
        id integer PRIMARY KEY, order_id integer NOT NULL REFERENCES orders(id),
        product_id integer NOT NULL REFERENCES products(id), quantity integer NOT NULL,
        unit_price numeric(10,2) NOT NULL, line_total numeric(12,2) NOT NULL)""",
    "CREATE INDEX ix_orders_order_date ON orders (order_date)",
    "CREATE INDEX ix_orders_customer ON orders (customer_id)",
    "CREATE INDEX ix_order_items_order ON order_items (order_id)",
    """CREATE VIEW monthly_revenue AS
        SELECT date_trunc('month', order_date)::date AS month, count(*) AS orders,
               sum(total_amount) AS revenue
        FROM orders WHERE status NOT IN ('cancelled', 'returned') GROUP BY 1""",
]


def build_shop(
    admin_url: str, reader_password: str, today: dt.date | None = None, reader: str = READER
) -> None:
    """Create and fill the shop database on PostgreSQL, and its read-only login."""
    rows = shop_rows(today or dt.date.today())
    engine = sa.create_engine(admin_url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with engine.begin() as c:
            for ddl in SHOP_DDL:
                c.exec_driver_sql(ddl)
            for table, data in rows.items():
                cols = {"customers": 6, "products": 4, "orders": 6, "order_items": 6}[table]
                marks = ", ".join(["%s"] * cols)
                c.exec_driver_sql(f"INSERT INTO {table} VALUES ({marks})", data)
            c.exec_driver_sql("ANALYZE")
            exists = c.exec_driver_sql(
                f"SELECT 1 FROM pg_roles WHERE rolname = '{reader}'"
            ).scalar()
            verb = "ALTER" if exists else "CREATE"
            c.exec_driver_sql(f"{verb} ROLE {reader} LOGIN PASSWORD '{_q(reader_password)}'")
            c.exec_driver_sql(f"GRANT CONNECT ON DATABASE {c.engine.url.database} TO {reader}")
            c.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {reader}")
            c.exec_driver_sql(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {reader}")
    finally:
        engine.dispose()


DEPARTMENTS = [
    (1, "Engineering", "Bengaluru"),
    (2, "Sales", "London"),
    (3, "Marketing", "New York"),
    (4, "Finance", "Frankfurt"),
    (5, "People", "Bengaluru"),
    (6, "Support", "Manila"),
    (7, "Product", "San Francisco"),
]
TITLES = {
    1: [
        ("Software Engineer", 95000),
        ("Senior Engineer", 135000),
        ("Staff Engineer", 175000),
        ("QA Engineer", 80000),
    ],
    2: [("Account Executive", 85000), ("Sales Manager", 120000), ("SDR", 55000)],
    3: [("Marketing Manager", 105000), ("Content Writer", 65000), ("Growth Analyst", 78000)],
    4: [("Accountant", 72000), ("Financial Analyst", 88000), ("Controller", 130000)],
    5: [("HR Partner", 76000), ("Recruiter", 68000)],
    6: [("Support Agent", 48000), ("Support Lead", 70000)],
    7: [("Product Manager", 140000), ("Designer", 105000), ("UX Researcher", 98000)],
}


def people_rows(today: dt.date) -> dict[str, list[tuple[Any, ...]]]:
    rng = random.Random(41)
    employees = []
    leaves = []
    leave_id = 0
    for eid in range(1, 321):
        dept = _pick(
            rng, [("1", 34), ("2", 18), ("3", 10), ("4", 8), ("5", 6), ("6", 14), ("7", 10)]
        )
        title, base = rng.choice(TITLES[int(dept)])
        first, last = rng.choice(FIRST), rng.choice(LAST)
        hire = _day(rng, dt.date(today.year - 7, 1, 1), today)
        status = _pick(rng, [("active", 86), ("on_leave", 5), ("terminated", 9)])
        employees.append(
            (
                eid,
                first,
                last,
                f"{first.lower()}.{last.lower()}{eid}@example.com",
                int(dept),
                title,
                hire,
                Decimal(str(round(base * rng.uniform(0.85, 1.25), -2))),
                next(d[2] for d in DEPARTMENTS if d[0] == int(dept)),
                status,
            )
        )
        for _ in range(rng.randint(0, 4)):
            leave_id += 1
            begin = _day(
                rng, max(hire, dt.date(today.year - 2, 1, 1)), today + dt.timedelta(days=60)
            )
            leaves.append(
                (
                    leave_id,
                    eid,
                    _pick(rng, [("vacation", 60), ("sick", 25), ("parental", 5), ("unpaid", 10)]),
                    begin,
                    rng.randint(1, 15),
                    _pick(rng, [("approved", 80), ("pending", 12), ("rejected", 8)]),
                )
            )
    return {"departments": list(DEPARTMENTS), "employees": employees, "leave_requests": leaves}


PEOPLE_DDL = [
    "DROP TABLE IF EXISTS leave_requests",
    "DROP TABLE IF EXISTS employees",
    "DROP TABLE IF EXISTS departments",
    """CREATE TABLE departments (
        id int PRIMARY KEY, name varchar(80) NOT NULL, location varchar(80) NOT NULL)""",
    """CREATE TABLE employees (
        id int PRIMARY KEY, first_name varchar(60) NOT NULL, last_name varchar(60) NOT NULL,
        email varchar(200) NOT NULL, department_id int NOT NULL, title varchar(80) NOT NULL,
        hire_date date NOT NULL, salary decimal(12,2) NOT NULL, city varchar(80) NOT NULL,
        status varchar(20) NOT NULL,
        CONSTRAINT fk_employees_department FOREIGN KEY (department_id) REFERENCES departments(id),
        INDEX ix_employees_hire_date (hire_date))""",
    """CREATE TABLE leave_requests (
        id int PRIMARY KEY, employee_id int NOT NULL, type varchar(20) NOT NULL,
        start_date date NOT NULL, days int NOT NULL, status varchar(20) NOT NULL,
        CONSTRAINT fk_leave_employee FOREIGN KEY (employee_id) REFERENCES employees(id))""",
]


def build_people(
    admin_url: str, reader_password: str, today: dt.date | None = None, reader: str = READER
) -> None:
    """Create and fill the people database on MySQL, and its read-only login."""
    rows = people_rows(today or dt.date.today())
    engine = sa.create_engine(admin_url.replace("mysql://", "mysql+pymysql://", 1))
    try:
        with engine.begin() as c:
            for ddl in PEOPLE_DDL:
                c.exec_driver_sql(ddl)
            for table, data in rows.items():
                cols = {"departments": 3, "employees": 10, "leave_requests": 6}[table]
                marks = ", ".join(["%s"] * cols)
                c.exec_driver_sql(f"INSERT INTO {table} VALUES ({marks})", data)
            c.exec_driver_sql("ANALYZE TABLE departments, employees, leave_requests")
            db = c.engine.url.database
            cur = c.connection.dbapi_connection.cursor()  # type: ignore[union-attr]
            # The raw cursor: with no parameters PyMySQL leaves the '%' host alone.
            cur.execute(
                f"CREATE USER IF NOT EXISTS '{reader}'@'%' IDENTIFIED BY '{_q(reader_password)}'"
            )
            cur.execute(f"ALTER USER '{reader}'@'%' IDENTIFIED BY '{_q(reader_password)}'")
            cur.execute(f"GRANT SELECT ON {db}.* TO '{reader}'@'%'")
    finally:
        engine.dispose()


PLANS = [
    (1, "Starter", Decimal("19.00")),
    (2, "Team", Decimal("79.00")),
    (3, "Business", Decimal("249.00")),
    (4, "Enterprise", Decimal("990.00")),
]
COMPANIES = [
    "Acme",
    "Globex",
    "Initech",
    "Umbrella",
    "Hooli",
    "Vandelay",
    "Stark",
    "Wayne",
    "Soylent",
    "Tyrell",
    "Cyberdyne",
    "Wonka",
    "Gringotts",
    "Pied Piper",
    "Aperture",
    "Monarch",
]
SUFFIXES = ["Labs", "Systems", "Foods", "Logistics", "Studio", "Health", "Capital", "Works"]


def subscriptions_rows(today: dt.date) -> dict[str, list[tuple[Any, ...]]]:
    rng = random.Random(7)
    accounts = []
    invoices = []
    inv = 0
    for aid in range(1, 241):
        plan = _pick(rng, [("1", 40), ("2", 32), ("3", 20), ("4", 8)])
        signed = _day(rng, dt.date(today.year - 2, 1, 1), today)
        status = _pick(rng, [("active", 72), ("trial", 10), ("churned", 18)])
        accounts.append(
            (
                aid,
                f"{rng.choice(COMPANIES)} {rng.choice(SUFFIXES)}",
                rng.choice(COUNTRIES),
                int(plan),
                status,
                signed.isoformat(),
            )
        )
        price = PLANS[int(plan) - 1][2]
        month = signed.replace(day=1)
        end = today if status != "churned" else _day(rng, signed, today)
        while month <= end and status != "trial":
            inv += 1
            paid = month + dt.timedelta(days=rng.randint(0, 20)) if rng.random() > 0.05 else None
            invoices.append(
                (inv, aid, float(price), month.isoformat(), paid.isoformat() if paid else None)
            )
            month = (month + dt.timedelta(days=32)).replace(day=1)
    return {
        "plans": [(p[0], p[1], float(p[2])) for p in PLANS],
        "accounts": accounts,
        "invoices": invoices,
    }


def build_subscriptions(path: Path, today: dt.date | None = None) -> Path:
    """Write the subscriptions database to a SQLite file and return its path."""
    rows = subscriptions_rows(today or dt.date.today())
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    try:
        db.executescript(
            """
            CREATE TABLE plans (id integer PRIMARY KEY, name text NOT NULL, monthly_price real NOT NULL);
            CREATE TABLE accounts (
                id integer PRIMARY KEY, company text NOT NULL, country text NOT NULL,
                plan_id integer NOT NULL REFERENCES plans(id), status text NOT NULL,
                signed_up date NOT NULL);
            CREATE TABLE invoices (
                id integer PRIMARY KEY, account_id integer NOT NULL REFERENCES accounts(id),
                amount real NOT NULL, issued_on date NOT NULL, paid_on date);
            CREATE INDEX ix_invoices_issued ON invoices (issued_on);
            """
        )
        db.executemany("INSERT INTO plans VALUES (?, ?, ?)", rows["plans"])
        db.executemany("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?)", rows["accounts"])
        db.executemany("INSERT INTO invoices VALUES (?, ?, ?, ?, ?)", rows["invoices"])
        db.commit()
    finally:
        db.close()
    return path


def _q(value: str) -> str:
    return value.replace("'", "''")
