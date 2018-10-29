import sqlite3
import re
import tabula
import csv
from datetime import datetime


def connect_db(sqlite_file):
    """
    Connect to database
    :param sqlite_file: filename of sqlite database
    :return: conn (sqlite connection), c (cursor)
    """
    conn = sqlite3.connect(sqlite_file)
    c = conn.cursor()
    return conn, c


def close_db(conn):
    """
    Commit all changes to database and close connection
    :param conn: sqlite connection
    :return:
    """
    conn.commit()
    conn.close()


def initialise_db(c, conn):
    # check if db exists, if so, warn user then abort
    c.execute('CREATE TABLE products('
              'barcode TEXT, '
              'product_code TEXT, '
              'last_update NUMERIC, '
              'primary_code NUMERIC, '
              'PRIMARY KEY (barcode))')
    c.execute('CREATE TABLE orders('
              'order_number INTEGER, '
              'internal_reference TEXT, '
              'PRIMARY KEY(order_number))')
    c.execute('CREATE TABLE scanned_products('
              'order_number INTEGER, '
              'product_code TEXT, '
              'expected_quantity INTEGER, '
              'scanned_quantity INTEGER, '
              'PRIMARY KEY (order_number, product_code), '
              'FOREIGN KEY (order_number) REFERENCES orders(order_number)'
              'ON DELETE CASCADE)')
    conn.commit()


def load_barcodes(c,conn):
    barcodes_file = input("CSV Filename:")
    try:
        with open(barcodes_file) as csvfile:
            readCSV = csv.reader(csvfile, delimiter=',')
            for row in readCSV:
                c.execute("SELECT count(*) "
                          "FROM products "
                          "WHERE barcode = ?",
                          (row[0],))
                if c.fetchone()[0] == 0:
                    c.execute("INSERT INTO products "
                              "VALUES(?,?,?,?)",
                              (row[0], row[1], row[2], row[3]))
        conn.commit()
    except FileNotFoundError as e:
        print("File does not exist:", e)


def load_pdf(c, conn):
    """
    Parses Order PDF and feeds data into the database
    :param c: sqlite cursor
    :param conn: sqlite connection
    :return:
    """
    pdf_name = input("PDF Filename:")
    try:
        order_num = None
        df_on = tabula.read_pdf(pdf_name, pages="1", area=[[40, 20, 535, 800]],
                                columns=[100, 210, 265, 325, 365, 440, 530, 590, 660, 710, 750, 800])
        for index, row in df_on.iterrows():
            if row[0] == "Customer Ord":
                print("Customer Order Number:", row[1], "Delivery Reference Number:", row[3])
                order_num = row[1]
                # check if exists in db, give user option to cancel
                c.execute("SELECT count(*) "
                          "FROM orders "
                          "WHERE order_number = ?",
                          (order_num,))
                if c.fetchone()[0] != 0:
                    print("Order", order_num, "already exists in database.")
                    while True:
                        confirmation = input("Continue to add products for scanning (y/n)?")
                        if confirmation == "n" or confirmation == "no" or confirmation == "back":
                            return
                        elif confirmation == "y" or confirmation == "yes":
                            break
                        else:
                            print("Invalid input, try again.")
                c.execute("INSERT INTO orders "
                          "VALUES(?,?)",
                          (row[1], row[3]))
                break

        df_pd = tabula.read_pdf(pdf_name, pages="all", area=[[40, 20, 535, 800]],
                                columns=[50, 160, 525, 600, 665, 700, 860])
        df_pd = df_pd.astype(str)
        header = ["Line", "Product Code", "Supplied Quantity"]
        row_format = "{:15}" * (len(header))
        print(row_format.format(*header))
        for index, row in df_pd.iterrows():
            if pn_regex_check(row[1]):
                print(row_format.format(row[0], row[1], row[4]))
                try:
                    quantity = int(row[4])
                except ValueError:
                    quantity = 0
                c.execute("SELECT count(*), expected_quantity "
                          "FROM scanned_products "
                          "WHERE order_number = ? AND product_code = ?",
                          (order_num, row[1]))
                rdata = c.fetchone()
                if rdata[0] != 0:
                    while True:
                        confirmation = input("Product already exists on order. "
                                             "Add quantity to supplied quantity? (y/n)?")
                        if confirmation == "n" or confirmation == "no" or confirmation == "back":
                            break
                        elif confirmation == "y" or confirmation == "yes":
                            c.execute("UPDATE scanned_products "
                                      "SET expected_quantity = ?"
                                      "WHERE order_number = ? AND product_code = ?",
                                      (rdata[1] + quantity, order_num, row[1]))
                            break
                        else:
                            print("Invalid input, try again.")
                else:
                    c.execute("INSERT INTO scanned_products "
                              "VALUES(?,?,?,0)",
                              (order_num, row[1], quantity))
        conn.commit()
    except FileNotFoundError as e:
        print("File does not exist:", e)



def add_barcode(c, conn):
    """
    Add a barcode linked to a product to the database
    :param c: sqlite cursor
    :param conn: sqlite connection
    :return:
    """
    # read input, check if barcode exists, if yes abort
    barcode = input('Input Barcode: ')
    c.execute("SELECT count(*) "
              "FROM products "
              "WHERE barcode = ?",
              (barcode,))
    count = c.fetchone()[0]
    if count == 0:
        product_code = input('Product Code: ')
        if pn_regex_check(product_code) is True:
            # valid product code, insert to db
            current_date = datetime.now().strftime("%d/%m/%Y")
            c.execute("INSERT INTO products "
                      "VALUES (?,?,?,'false')",
                      (barcode, product_code.upper(), current_date,))
            conn.commit()
            print(product_code.upper(), 'added to database.')
        else:
            print("Invalid product code. Must be 2 letters followed by 4 numbers.")
    else:
        print('Barcode already exists in system.')


def remove_barcode(c, conn):
    """
    Remove a barcode linked to a product to the database
    :param c: sqlite cursor
    :param conn: sqlite connection
    :return:
    """
    barcode = input('Input Barcode: ')
    c.execute("SELECT count(*) "
              "FROM products "
              "WHERE barcode = ?",
              (barcode,))
    count = c.fetchone()[0]
    if count != 0:
        c.execute('DELETE FROM products '
                  'WHERE barcode = ?',
                  (barcode,))
        conn.commit()
        print('Barcode has been removed from database.')
    else:
        print('Barcode is not in the database. Unable to remove')


def validate_order_input(c):
    """
    Checks if user input is a valid delivery reference (e.g. SJ532017) or a valid customer order number (e.g. 40408133)
    It is valid if it exists in the database
    :param c: sqlite cursor
    :return: returns None if the user wants to go back to the main menu, otherwise returns the customer order number
    """
    while True:
        ref = input('Input Delivery Reference or Customer Order Number:')
        if ref == "exit" or ref == "back":
            return None
        c.execute("SELECT count(*) "
                  "FROM orders "
                  "WHERE internal_reference = ?",
                  (ref,))
        internal_ref_count = c.fetchone()
        if internal_ref_count[0] > 1:
            print("Delivery Reference is linked to multiple orders, try again with Customer Order Number")
        elif internal_ref_count[0] == 0:
            c.execute("SELECT count(*) "
                      "FROM orders "
                      "WHERE order_number= ?", (ref,))
            if c.fetchone()[0] != 0:
                break
            else:
                print("Order number does not exist in system, try again.")
        else:
            c.execute("SELECT order_number "
                      "FROM orders "
                      "WHERE internal_reference = ?", (ref,))
            ref = c.fetchone()[0]
            break
    return ref


def check_order(c):
    """
    Print off a report of a specific order
    :param c: sqlite cursor
    :return:
    """
    order_num = validate_order_input(c)
    if order_num is not None:
        print_report(c, order_num)


def scan_order(c, conn):
    """
    Function for stock checking
    User will either scan barcodes (increments scanned quantity by 1) or manually inputting a product code and quantity
    :param c: sqlite cursor
    :param conn: sqlite connection
    :return:
    """
    order_num = validate_order_input(c)
    if order_num is None:
        print("Order does not exist in database.")
        return
    while True:
        input_code = input('Barcode or Product Code:')
        if input_code == "finish" or input_code == "end":
            break
        # Check if input a valid barcode in the database
        c.execute("SELECT product_code "
                  "FROM products "
                  "WHERE barcode = ?",
                  (input_code,))
        product_code = c.fetchone()
        # If input is not barcode in database, then go through steps to check if it is a valid product code input
        if product_code is None:
            input_code = input_code.upper()
            if pn_regex_check(input_code) is False:
                print("ERROR: Barcode does not exist in database or "
                      "Product Code is invalid formatting (2 letters, 4 digits).")
                continue
            # Check if product code exists on order
            c.execute("SELECT count(*), scanned_quantity "
                      "FROM scanned_products "
                      "WHERE order_number = ? "
                      "AND product_code = ?",
                      (order_num, input_code,))
            on_order = c.fetchone()
            # If product code does not exist on the order, ask user if they want to force add
            if on_order[0] == 0:
                while True:
                    add_to_order = input(input_code + " is not on the order list. Force add to order (y/n)?")
                    if add_to_order == "y" or add_to_order == "yes":
                        quantity = get_quantity()
                        if quantity is None:
                            break
                        else:
                            c.execute("INSERT INTO scanned_products "
                                      "VALUES(?,?,0,?)",
                                      (order_num, input_code, quantity,))
                            break
                    elif add_to_order == "n" or add_to_order == "no":
                        break
                    else:
                        print("Try again, valid input is 'y' or 'n'")
            # If product code does exists on the order, ask user what quantity they want to add
            else:
                quantity = get_quantity()
                if quantity is None:
                    continue
                else:
                    c.execute("UPDATE scanned_products "
                              "SET scanned_quantity = ? "
                              "WHERE order_number = ? AND product_code = ?",
                              (quantity + on_order[1], order_num, input_code,))
        else:
            c.execute("SELECT scanned_quantity "
                      "FROM scanned_products "
                      "WHERE product_code = ?",
                      (product_code[0],))
            s_quantity = c.fetchone()
            c.execute("UPDATE scanned_products "
                      "SET scanned_quantity = ? "
                      "WHERE order_number = ? AND product_code = ?",
                      (s_quantity[0]+1, order_num, product_code[0],))
        conn.commit()
        # Print updated quantity for product code just inputted
    print_report(c, order_num)


def print_report(c, order_number):
    """
    Prints out all the data associated with a specific order number
    Also calculates the difference between expected and scanned quantities to see if any stock is missing
    :param c: cursor for sqlite3
    :param order_number: the customer order number to print out from the database
    :return:
    """
    c.execute("SELECT product_code, expected_quantity, scanned_quantity "
              "FROM scanned_products "
              "WHERE order_number = ? "
              "ORDER BY product_code ASC", (order_number,))
    data = c.fetchall()
    header = ["Product Code", "Expected Quantity", "Scanned Quantity", "Difference"]
    row_format = "{:^20}" * (len(header))
    print(row_format.format(*header))
    for row in data:
        dif = row[2] - row[1]
        print(row_format.format(*row, dif))


def print_productsdb(c):
    """
    Prints out all products that are linked to a barcode in the database
    :param c: cursor for sqlite3
    :return:
    """
    c.execute("SELECT * FROM products ORDER BY product_code ASC")
    data = c.fetchall()
    header = ["Barcode", "Product Code", "Last Update", "Primary Code"]
    row_format = "{:^35}" * (len(header))
    print(row_format.format(*header))
    for row in data:
        print(row_format.format(*row))


def pn_regex_check(p_code):
    """
    Verify that the provided string uses the valid formatting for a product code
    Formatting is 2 letters followed by 4 numbers
    :param p_code: string to validate
    :return: boolean (True or False)
    """
    regex = re.compile("^[a-zA-Z]{2}[0-9]{4}$")
    if regex.match(p_code):
        return True
    else:
        return False


def get_quantity():
    """
    Checks if user input is an integer
    :return: quantity if input is valid integer, or None if user cancels the command
    """
    while True:
        try:
            user_input = input("Quantity:")
            if user_input == "cancel" or user_input == "back":
                return None
            else:
                quantity = int(user_input)
                return quantity
        except ValueError:
            print("Input was not an integer. Aborted.")
            return None


def remove_order(c, conn):
    """
    Removes specified order from the database
    :param c: cursor for sqlite3
    :param conn: sqlite3 connection
    :return:
    """
    order_number = input("Input Customer Order Number to delete from database:")
    c.execute("SELECT count(*) "
              "FROM orders "
              "WHERE order_number = ?", (order_number,))
    if c.fetchone()[0] != 0:
        c.execute("DELETE FROM orders "
                  "WHERE order_number = ?", (order_number,))
        conn.commit()
    else:
        print("Order number does not exist in system.")


def adj_supplied_quantity(c, conn):
    """
    Adjusts the supplied quantity if the product exists on the order, or adds the product to the order list if it
    doesn't exist on the order (and the user confirms)
    :param c: cursor for sqlite3
    :param conn:  sqlite connection
    :return:
    """
    order_number = input("Input Customer Order Number:")
    c.execute("SELECT count(*) "
              "FROM orders "
              "WHERE order_number = ?", (order_number,))
    if c.fetchone()[0] != 0:
        prod_c = input("Product number to amend:")
        if pn_regex_check(prod_c):
            try:
                quantity = int(input("Change supplied quantity to:"))
            except ValueError:
                print("Invalid input (not integer). Back to main menu.")
                return
            c.execute("SELECT count(*), expected_quantity "
                      "FROM scanned_products "
                      "WHERE order_number = ? AND product_code = ?", (order_number, prod_c,))
            if c.fetchone()[0] != 0:
                c.execute("UPDATE scanned_products "
                          "SET expected_quantity = ? "
                          "WHERE order_number = ? AND product_code = ?", (quantity, order_number, prod_c,))
            else:
                conf = input("Product is not on order. Add to order (y to confirm, anything else for no)?")
                if conf == "y" or conf == "yes":
                    c.execute("INSERT INTO scanned_products "
                              "VALUES(?,?,?,0)", (order_number, prod_c, quantity,))
                else:
                    return
            conn.commit()
        else:
            print("Invalid product number. Back to main menu.")
    else:
        print("Order number does not exist in system.")


def list_orders(c):
    """
    Lists all the orders in the database
    :param c: cursor for sqlite3
    :return:
    """
    c.execute("SELECT * "
              "FROM orders "
              "ORDER BY order_number ASC")
    data = c.fetchall()
    header = ["Customer Order Number", "Delivery Reference Number"]
    row_format = "{:^30}" * (len(header))
    print(row_format.format(*header))
    for row in data:
        print(row_format.format(*row))


def main():
    sqlite_file = 'database.db'
    conn, c = connect_db(sqlite_file)
    while True:
        cmd = input('>')
        # check if db exists, if not fail to read any commands tell user to type initialise
        if cmd == "load pdf":
            load_pdf(c, conn)
        elif cmd == "scan":
            scan_order(c, conn)
        elif cmd == "add barcode":
            add_barcode(c, conn)
        elif cmd == "remove barcode":
            remove_barcode(c, conn)
        elif cmd == "exit":
            break
        elif cmd == "initialise":
            initialise_db(c, conn)
        elif cmd == "check order":
            check_order(c)
        elif cmd == "remove order":
            remove_order(c, conn)
        elif cmd == "list orders":
            list_orders(c)
        elif cmd == "load barcodes":
            load_barcodes(c, conn)
        elif cmd == "?" or cmd == "help":
            print("List of commands: load pdf, scan, add barcode, remove barcode, check order, "
                  "remove order, list orders, adjust quantity, exit")
        else:
            print("invalid input")
    conn.close()


if __name__ == '__main__':
    main()
