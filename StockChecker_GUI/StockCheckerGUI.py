from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty
from kivy.clock import Clock
from kivy.uix.popup import Popup
import sqlite3
import re
import tabula
import csv
from datetime import datetime
from kivy.core.window import Window

Window.softinput_mode = 'pan'

conn = sqlite3.connect('database.db')
c = conn.cursor()


class MenuScreen(Screen):
    def __init__(self, **kwargs):
        super(MenuScreen, self).__init__(**kwargs)
        # do database check on startup
        Clock.schedule_once(self.init_ui, 0)

    def init_ui(self, dt=0):
        if database_check():
            self.ids.verifyorderbutton.disabled = False
            self.ids.checkorderbutton.disabled = False
            self.ids.importpdfbutton.disabled = False
        else:
            self.ids.verifyorderbutton.disabled = True
            self.ids.checkorderbutton.disabled = True
            self.ids.importpdfbutton.disabled = True


class AdvancedScreen(Screen):
    def __init__(self, **kwargs):
        super(AdvancedScreen, self).__init__(**kwargs)

    def init_ui(self, dt=0):
        if database_check():
            self.ids.initalisedbbutton.disabled = True
            self.ids.import_csv.disabled = False
            self.ids.export_csv.disabled = False
            self.ids.add_bar.disabled = False
            self.ids.rm_bar.disabled = False
        else:
            self.ids.initalisedbbutton.disabled = False
            self.ids.import_csv.disabled = True
            self.ids.export_csv.disabled = True
            self.ids.add_bar.disabled = True
            self.ids.rm_bar.disabled = True

    def initialise_db(self):
        initialise_db()

    def import_barcodes(self):
        load_popup = LoadingPopup()
        load_popup.open()

    def export_barcodes(self):
        export_popup = ExportPopup()
        export_popup.open()


class ImportPDFScreen(Screen):
    def __init__(self, **kwargs):
        super(ImportPDFScreen, self).__init__(**kwargs)

    def start_import(self):
        load_pdf(str(self.ids.file_chooser.selection[0]))

    def refresh_view(self):
        self.ids.file_chooser._update_files()


class CheckOrderScreen(Screen):
    data_items = ListProperty([])
    order_number = None

    def __init__(self,**kwargs):
        super(CheckOrderScreen, self).__init__(**kwargs)


    def _on_keyboard_down(self, instance, keyboard, keycode, text, modifiers):
        if self.ids.scaninput.focus and keycode == 40:  # 40 - Enter key pressed
            self.add_to_db()

    def load_order(self):
        order_num = validate_order_input(self.ids.checkordernum.text)
        if order_num is not None:
            c.execute("SELECT * "
                      "FROM scanned_products "
                      "WHERE order_number = ? "
                      "ORDER BY product_code ASC", (order_num,))
            rows = c.fetchall()
            data = []
            for row in rows:
                for col in row:
                    data.append([col])
                data.append([int(data[-1][0]) - int(data[-2][0])])
            self.data_items = [{'text': str(x[0])} for x in data]
            self.order_number = order_num

    def add_to_db(self):
        # check if quantity is integer, could do through kivy but it only forces positive numbers
        # negative numbers required if mistakes are made when entering quantities
        quantity = get_quantity(self.ids.quantity.text)
        if self.order_number is not None and quantity is not None:
            # logic = if barcode or product number, and on order, read quantity textbox and add to db
            # logic = if not valid product code --> if barcode not exist on system -->
            # ask if user wants to add to DB (POPUP)
            # then add thing to db
            # logic = if valid product code but not on order, ask user if force add to DB (POPUP)
            c.execute("SELECT product_code "
                      "FROM products "
                      "WHERE barcode = ?",
                      (self.ids.scaninput.text,))
            product_code = c.fetchone()
            if product_code is None:
                # Barcode does not exist in system
                if pn_regex_check(self.ids.scaninput.text) is False:
                    # Not a valid Product Code, ask user if they want to add to DB as a barcode
                    # popup --> add to barcode db, back to main screen
                    abp_popup = AddBarcodePopup()
                    abp_popup.open()
                    abp_popup.disable_barcode(self.ids.scaninput.text)
                    return
                else:
                    # is valid product code, check if on order
                    return_chk = is_on_order(self.order_number, self.ids.scaninput.text.upper())
                    if return_chk[0]:
                        # on order, add to db
                        update_order(self.order_number, self.ids.scaninput.text.upper(), return_chk[1]+quantity)
                        # update gui --> search through data_items and adjust the vals
                        for idx, item in enumerate(self.data_items):
                            if self.data_items[idx] == {'text': self.ids.scaninput.text.upper()}:
                                self.data_items[idx+2] = {'text': str(return_chk[1]+quantity)}
                                self.data_items[idx+3] = {'text': str(int(self.data_items[idx + 3]['text']) + quantity)}
                                break
                        self.update_labels(self.ids.scaninput.text.upper(), quantity)
                    else:
                        # not on order, popup -> force add to order? (yes, no)
                        force_add_popup = ForceAddProductToOrderPopup(order_number=self.order_number,
                                                                      product_code=self.ids.scaninput.text.upper(),
                                                                      quantity=quantity,
                                                                      caller=self)
                        force_add_popup.open()
            else:
                # this is if barcode is in db
                return_chk = is_on_order(self.order_number, product_code[0])
                if return_chk[0]:
                    # on order, add to db
                    update_order(self.order_number, product_code[0], return_chk[1]+quantity)
                    # update gui --> search through data_items and adjust the vals
                    for idx, item in enumerate(self.data_items):
                        if self.data_items[idx] == {'text': product_code[0]}:
                            self.data_items[idx + 2] = {'text': str(return_chk[1] + quantity)}
                            self.data_items[idx + 3] = {'text': str(int(self.data_items[idx + 3]['text']) + quantity)}
                            break
                    self.update_labels(product_code[0], quantity)
                else:
                    # not on order, popup -> force add to order? (yes, no)
                    force_add_popup = ForceAddProductToOrderPopup(order_number=self.order_number,
                                                                  product_code=product_code[0],
                                                                  quantity=quantity,
                                                                  caller=self)
                    force_add_popup.open()
            self.ids.quantity.text = '1'
            self.ids.scaninput.text = ''

    def update_labels(self, prod_code, entered_quantity):
        self.ids.last_entered_item.text = str(prod_code)
        self.ids.last_entered_quantity.text = str(entered_quantity)


class VerifyOrderScreen(Screen):
    data_items = ListProperty([])

    def __init__(self,**kwargs):
        super(VerifyOrderScreen, self).__init__(**kwargs)
        #Window.bind(on_key_down=self._on_keyboard_down)

    def _on_keyboard_down(self, instance, keyboard, keycode, text, modifiers):
        if self.ids.verifyordernum.focus and keycode == 40:  # 40 - Enter key pressed
            self.search_order()

    def search_order(self):
        order_num = validate_order_input(self.ids.verifyordernum.text)
        if order_num is not None:
            c.execute("SELECT * "
                      "FROM scanned_products "
                      "WHERE order_number = ? "
                      "ORDER BY product_code ASC", (order_num,))
            rows = c.fetchall()
            data = []
            for row in rows:
                for col in row:
                    data.append([col])
                data.append([int(data[-1][0]) - int(data[-2][0])])
                if self.ids.verifychkbox.active and data[-1][0] == 0:
                    del data[-5:]
            self.data_items = [{'text': str(x[0])} for x in data]

    def print_to_pdf(self):
        pass


class ExportPopup(Popup):
    def __init__(self, **kwargs):
        super(ExportPopup, self).__init__(**kwargs)

    def start_export(self):
        if export_barcodes(self.ids.export_filename.text + ".csv"):
            self.dismiss()
        else:
            self.ids.export_warning.text = 'Failed to Export'


class LoadingPopup(Popup):
    def __init__(self, **kwargs):
        super(LoadingPopup, self).__init__(**kwargs)

    def import_barcodes(self):
        if load_barcodes(self.ids.file_chooser.selection):
            self.dismiss()
        else:
            self.ids.import_warning.text = 'Failed to Import'

    def refresh_view(self):
        self.ids.file_chooser._update_files()


class AddBarcodePopup(Popup):
    def __init__(self, **kwargs):
        super(AddBarcodePopup, self).__init__(**kwargs)

    def disable_barcode(self, barcode):
        self.ids.add_bc_barcode.text = barcode
        self.ids.add_bc_barcode.disabled = True

    def save_barcode(self):
        # regex check textbox of product code
        if pn_regex_check(self.ids.add_bc_product_code.text):
            # add to db
            add_barcode(self.ids.add_bc_barcode.text,self.ids.add_bc_product_code.text)
            self.dismiss()
        else:
            self.ids.warning_label.text = 'INVALID PRODUCT CODE FORMAT\nUSE 2 LETTERS\nFOLLOWED BY 4 NUMBERS'


class RemoveBarcodePopup(Popup):
    def __init__(self, **kwargs):
        super(RemoveBarcodePopup, self).__init__(**kwargs)

    def remove_barcode(self):
        if remove_barcode(self.ids.rm_bc_barcode.text):
            self.dismiss()
        else:
            self.ids.rm_warning_label.text = 'BARCODE NOT IN DATABASE\nCANCEL OR TRY AGAIN'
            self.ids.rm_bc_barcode.text = ''


class ForceAddProductToOrderPopup(Popup):
    caller = None

    def __init__(self, **kwargs):
        self.caller = kwargs.get('caller')
        super(ForceAddProductToOrderPopup, self).__init__()
        self.ids.title_product_code.text = kwargs.get('product_code')
        self.ids.title_order_number.text = kwargs.get('order_number')
        self.ids.body_product_code.text = kwargs.get('product_code')
        self.ids.body_quantity.text = str(kwargs.get('quantity'))

    def add_to_order(self):
        # add to DB
        add_to_order(self.ids.title_order_number.text, self.ids.title_product_code.text, self.ids.body_quantity.text)
        # update gui -->  self.data_items.append({'text': '40408133'}) etc
        self.caller.data_items.append({'text': self.ids.title_order_number.text})
        self.caller.data_items.append({'text': self.ids.title_product_code.text})
        self.caller.data_items.append({'text': '0'})
        self.caller.data_items.append({'text': self.ids.body_quantity.text})
        self.caller.data_items.append({'text': self.ids.body_quantity.text})
        self.caller.ids.last_entered_item.text = self.ids.title_product_code.text
        self.caller.ids.last_entered_quantity.text = self.ids.body_quantity.text
        self.dismiss()


class StockChecker(App):
    pass


def add_to_order(order_number, product_code, quantity):
    c.execute("INSERT INTO scanned_products "
              "VALUES(?,?,0,?)",
              (order_number, product_code, quantity,))
    conn.commit()


def update_order(order_number, product_code, new_quantity):
    c.execute("UPDATE scanned_products "
              "SET scanned_quantity = ? "
              "WHERE order_number = ? AND product_code = ?",
              (new_quantity, order_number, product_code,))
    conn.commit()


def is_on_order(order_number, product_code):
    c.execute("SELECT count(*), scanned_quantity "
              "FROM scanned_products "
              "WHERE order_number = ? "
              "AND product_code = ?",
              (order_number, product_code,))
    on_order = c.fetchone()
    if on_order[0] == 0:
        return [False, 0]
    else:
        return [True, on_order[1]]


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


def get_quantity(input_string):
    """
    Checks if user input is an integer
    :return: quantity if input is valid integer, or None if user cancels the command
    """
    while True:
        try:
            quantity = int(input_string)
            return quantity
        except ValueError:
            return None


def validate_order_input(order_num):
    """
    Checks if user input is a valid delivery reference (e.g. SJ532017) or a valid customer order number (e.g. 40408133)
    It is valid if it exists in the database
    :param order_num: sqlite cursor
    :return: returns None if the user wants to go back to the main menu, otherwise returns the customer order number
    """
    c.execute("SELECT count(*) "
              "FROM orders "
              "WHERE internal_reference = ?",
              (order_num.upper(),))
    internal_ref_count = c.fetchone()
    if internal_ref_count[0] > 1:
        print("Delivery Reference is linked to multiple orders, try again with Customer Order Number")
        return None
    elif internal_ref_count[0] == 0:
        c.execute("SELECT count(*) "
                  "FROM orders "
                  "WHERE order_number= ?", (order_num,))
        if c.fetchone()[0] != 0:
            return order_num
        else:
            print("Order number does not exist in system, try again.")
            return None
    else:
        c.execute("SELECT order_number "
                  "FROM orders "
                  "WHERE internal_reference = ?", (order_num.upper(),))
        order_num = c.fetchone()[0]
        return order_num


def add_barcode(barcode, product_code):
    """
    Add a barcode linked to a product to the database
    :return:
    """
    # read input, check if barcode exists, if yes abort
    c.execute("SELECT count(*) "
              "FROM products "
              "WHERE barcode = ?",
              (barcode,))
    count = c.fetchone()[0]
    if count == 0:
        if pn_regex_check(product_code) is True:
            # valid product code, insert to db
            current_date = datetime.now().strftime("%d/%m/%Y")
            c.execute("INSERT INTO products "
                      "VALUES (?,?,?,'false')",
                      (barcode, product_code.upper(), current_date,))
            conn.commit()
            # print(product_code.upper(), 'added to database.')
            return True
        else:
            # print("Invalid product code. Must be 2 letters followed by 4 numbers.")
            return False
    else:
        # print('Barcode already exists in system.')
        return False


def remove_barcode(barcode):
    """
    Remove a barcode linked to a product to the database
    :return:
    """
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
        # print('Barcode has been removed from database.')
        return True
    else:
        # print('Barcode is not in the database. Unable to remove')
        return False


def load_pdf(pdf):
    """
    Parses Order PDF and feeds data into the database
    :return:
    """
    try:
        order_num = None
        df_on = tabula.read_pdf(pdf, pages="1", area=[[40, 20, 535, 800]],
                                columns=[100, 210, 265, 325, 365, 440, 530, 590, 660, 710, 750, 800])
        for index, row in df_on.iterrows():
            if row[0] == "Customer Ord":
                print("Customer Order Number:", row[1], "Delivery Reference Number:", row[3])
                order_num = row[1]
                # check if exists in db, cancel...
                c.execute("SELECT count(*) "
                          "FROM orders "
                          "WHERE order_number = ?",
                          (order_num,))
                if c.fetchone()[0] != 0:
                    print("Order", order_num, "already exists in database.")
                    return
                c.execute("INSERT INTO orders "
                          "VALUES(?,?)",
                          (row[1], row[3]))
                break

        df_pd = tabula.read_pdf(pdf, pages="all", area=[[40, 20, 535, 800]],
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
                    c.execute("UPDATE scanned_products "
                              "SET expected_quantity = ?"
                              "WHERE order_number = ? AND product_code = ?",
                              (rdata[1] + quantity, order_num, row[1]))
                else:
                    c.execute("INSERT INTO scanned_products "
                              "VALUES(?,?,?,0)",
                              (order_num, row[1], quantity))
        conn.commit()
    except FileNotFoundError as e:
        print("File does not exist:", e)


def load_barcodes(barcodes_csv_file):
    try:
        #check formatting of csv file, first column could be anything. 2nd do regex, 3rd do datetime check
        with open(barcodes_csv_file) as csv_file:
            read_csv = csv.reader(csv_file, delimiter=',')
            for row in read_csv:
                c.execute("SELECT count(*) "
                          "FROM products "
                          "WHERE barcode = ?",
                          (row[0],))
                if c.fetchone()[0] == 0:
                    c.execute("INSERT INTO products "
                              "VALUES(?,?,?,?)",
                              (row[0], row[1], row[2], row[3]))
        conn.commit()
        return True
    except Exception as e:
        print("File does not exist:", e)
        return False


def export_barcodes(barcodes_csv_file):
    try:
        c.execute('SELECT * FROM products')
        with open(barcodes_csv_file, 'w', newline="") as output_file:
            writer = csv.writer(output_file)
            for result in c:
                writer.writerow(result)
        return True
    except Exception as e:
        print(e)
        return False


def initialise_db():
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


def database_check():
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products';")
    prod_chk = bool(c.fetchone())
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders';")
    order_chk = bool(c.fetchone())
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='scanned_products';")
    scanned_prod_chk = bool(c.fetchone())
    if prod_chk and order_chk and scanned_prod_chk:
        return True
    else:
        return False


if __name__ == '__main__':
    StockChecker().run()
