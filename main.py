#!/usr/bin/env python3
"""
Inventory Management System
---------------------------
A simple command-line inventory manager using only the Python standard library
(SQLite for storage). Features:

  * Add / edit / delete products
  * Stock in / stock out with a full transaction history
  * Search and list products
  * Low-stock alerts and inventory valuation report
  * CSV export

Run:  python inventory_system.py
"""

import csv
import sqlite3
from datetime import datetime

DB_FILE = "inventory.db"


# ---------------------------------------------------------------- database --
class Inventory:
    def __init__(self, db_file=DB_FILE):
        self.conn = sqlite3.connect(db_file)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                sku           TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                category      TEXT DEFAULT 'General',
                quantity      INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                unit_price    REAL NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
                reorder_level INTEGER NOT NULL DEFAULT 5,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                sku       TEXT NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
                change    INTEGER NOT NULL,
                reason    TEXT,
                timestamp TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    # -- products ----------------------------------------------------------
    def add_product(self, sku, name, category, quantity, unit_price, reorder_level):
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sku, name, category, quantity, unit_price, reorder_level, now),
                )
                if quantity:
                    self._log(sku, quantity, "Initial stock")
        except sqlite3.IntegrityError:
            raise ValueError(f"A product with SKU '{sku}' already exists.")

    def get_product(self, sku):
        row = self.conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
        if row is None:
            raise ValueError(f"No product with SKU '{sku}'.")
        return row

    def update_product(self, sku, **fields):
        self.get_product(sku)  # raises if missing
        allowed = {"name", "category", "unit_price", "reorder_level"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.conn:
            self.conn.execute(
                f"UPDATE products SET {assignments} WHERE sku = ?",
                (*fields.values(), sku),
            )

    def delete_product(self, sku):
        self.get_product(sku)
        with self.conn:
            self.conn.execute("DELETE FROM products WHERE sku = ?", (sku,))

    def list_products(self, search=None):
        if search:
            like = f"%{search}%"
            return self.conn.execute(
                """SELECT * FROM products
                   WHERE sku LIKE ? OR name LIKE ? OR category LIKE ?
                   ORDER BY name""",
                (like, like, like),
            ).fetchall()
        return self.conn.execute("SELECT * FROM products ORDER BY name").fetchall()

    # -- stock movements -----------------------------------------------------
    def _log(self, sku, change, reason):
        self.conn.execute(
            "INSERT INTO transactions (sku, change, reason, timestamp) VALUES (?, ?, ?, ?)",
            (sku, change, reason, datetime.now().isoformat(timespec="seconds")),
        )

    def adjust_stock(self, sku, change, reason=""):
        product = self.get_product(sku)
        new_qty = product["quantity"] + change
        if new_qty < 0:
            raise ValueError(
                f"Insufficient stock: only {product['quantity']} unit(s) of '{product['name']}' available."
            )
        with self.conn:
            self.conn.execute("UPDATE products SET quantity = ? WHERE sku = ?", (new_qty, sku))
            self._log(sku, change, reason or ("Stock in" if change > 0 else "Stock out"))
        return new_qty

    def history(self, sku=None, limit=20):
        query = """SELECT t.timestamp, t.sku, p.name, t.change, t.reason
                   FROM transactions t JOIN products p ON p.sku = t.sku"""
        params = []
        if sku:
            query += " WHERE t.sku = ?"
            params.append(sku)
        query += " ORDER BY t.id DESC LIMIT ?"
        params.append(limit)
        return self.conn.execute(query, params).fetchall()

    # -- reports -------------------------------------------------------------
    def low_stock(self):
        return self.conn.execute(
            "SELECT * FROM products WHERE quantity <= reorder_level ORDER BY quantity"
        ).fetchall()

    def valuation(self):
        row = self.conn.execute(
            "SELECT COUNT(*) AS items, COALESCE(SUM(quantity),0) AS units, "
            "COALESCE(SUM(quantity * unit_price),0) AS value FROM products"
        ).fetchone()
        return dict(row)

    def export_csv(self, path="inventory_export.csv"):
        rows = self.list_products()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["SKU", "Name", "Category", "Quantity", "Unit Price",
                             "Reorder Level", "Stock Value"])
            for r in rows:
                writer.writerow([r["sku"], r["name"], r["category"], r["quantity"],
                                 f"{r['unit_price']:.2f}", r["reorder_level"],
                                 f"{r['quantity'] * r['unit_price']:.2f}"])
        return path, len(rows)


# --------------------------------------------------------------------- CLI --
def print_products(rows):
    if not rows:
        print("  (no products found)")
        return
    header = f"{'SKU':<10}{'Name':<25}{'Category':<15}{'Qty':>6}{'Price':>10}{'Reorder':>9}"
    print(header)
    print("-" * len(header))
    for r in rows:
        flag = "  <-- LOW" if r["quantity"] <= r["reorder_level"] else ""
        print(f"{r['sku']:<10}{r['name'][:24]:<25}{r['category'][:14]:<15}"
              f"{r['quantity']:>6}{r['unit_price']:>10.2f}{r['reorder_level']:>9}{flag}")


def ask_int(prompt, default=None, minimum=0):
    while True:
        raw = input(prompt).strip()
        if raw == "" and default is not None:
            return default
        try:
            value = int(raw)
            if value < minimum:
                raise ValueError
            return value
        except ValueError:
            print(f"  Please enter a whole number >= {minimum}.")


def ask_float(prompt, default=None):
    while True:
        raw = input(prompt).strip()
        if raw == "" and default is not None:
            return default
        try:
            value = float(raw)
            if value < 0:
                raise ValueError
            return value
        except ValueError:
            print("  Please enter a non-negative number.")


MENU = """
===== INVENTORY MANAGEMENT SYSTEM =====
 1. Add product
 2. List all products
 3. Search products
 4. Update product details
 5. Delete product
 6. Stock in (receive)
 7. Stock out (sell / remove)
 8. Transaction history
 9. Low-stock report
10. Inventory valuation
11. Export to CSV
 0. Exit
"""


def main():
    inv = Inventory()
    while True:
        print(MENU)
        choice = input("Choose an option: ").strip()
        try:
            if choice == "1":
                sku = input("SKU: ").strip().upper()
                name = input("Name: ").strip()
                if not sku or not name:
                    raise ValueError("SKU and name are required.")
                category = input("Category [General]: ").strip() or "General"
                qty = ask_int("Initial quantity [0]: ", default=0)
                price = ask_float("Unit price [0]: ", default=0.0)
                reorder = ask_int("Reorder level [5]: ", default=5)
                inv.add_product(sku, name, category, qty, price, reorder)
                print(f"Added '{name}'.")

            elif choice == "2":
                print_products(inv.list_products())

            elif choice == "3":
                print_products(inv.list_products(input("Search term: ").strip()))

            elif choice == "4":
                sku = input("SKU to update: ").strip().upper()
                p = inv.get_product(sku)
                print("Leave a field blank to keep its current value.")
                name = input(f"Name [{p['name']}]: ").strip() or None
                category = input(f"Category [{p['category']}]: ").strip() or None
                price = ask_float(f"Unit price [{p['unit_price']:.2f}]: ", default=p["unit_price"])
                reorder = ask_int(f"Reorder level [{p['reorder_level']}]: ", default=p["reorder_level"])
                inv.update_product(sku, name=name, category=category,
                                   unit_price=price, reorder_level=reorder)
                print("Product updated.")

            elif choice == "5":
                sku = input("SKU to delete: ").strip().upper()
                p = inv.get_product(sku)
                if input(f"Delete '{p['name']}' and its history? (y/N): ").lower() == "y":
                    inv.delete_product(sku)
                    print("Product deleted.")

            elif choice in ("6", "7"):
                sku = input("SKU: ").strip().upper()
                p = inv.get_product(sku)
                print(f"{p['name']} - current stock: {p['quantity']}")
                amount = ask_int("Quantity: ", minimum=1)
                reason = input("Reason / reference (optional): ").strip()
                change = amount if choice == "6" else -amount
                new_qty = inv.adjust_stock(sku, change, reason)
                print(f"Done. New stock level: {new_qty}")
                if new_qty <= p["reorder_level"]:
                    print("  Warning: stock is at or below the reorder level!")

            elif choice == "8":
                sku = input("SKU (blank for all): ").strip().upper() or None
                rows = inv.history(sku)
                if not rows:
                    print("  (no transactions)")
                for r in rows:
                    print(f"{r['timestamp']}  {r['sku']:<10}{r['name'][:20]:<21}"
                          f"{r['change']:>+6}  {r['reason']}")

            elif choice == "9":
                rows = inv.low_stock()
                print_products(rows) if rows else print("All items are sufficiently stocked.")

            elif choice == "10":
                v = inv.valuation()
                print(f"Distinct products : {v['items']}")
                print(f"Total units       : {v['units']}")
                print(f"Total stock value : {v['value']:,.2f}")

            elif choice == "11":
                path, count = inv.export_csv()
                print(f"Exported {count} products to {path}")

            elif choice == "0":
                print("Goodbye!")
                break

            else:
                print("Invalid option, try again.")

        except ValueError as err:
            print(f"Error: {err}")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break


if __name__ == "__main__":
    main()
