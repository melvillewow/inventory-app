from collections import defaultdict
from datetime import date


WAREHOUSES = ["Club", "House"]


class InventorySystem:
    def __init__(self):
        # location -> item -> quantity
        self.stock = defaultdict(lambda: defaultdict(int))
        self.vans = [f"Van_{i}" for i in range(1, 11)]
        self.van_nicknames = {}
        self.nickname_date = date.today()
        self._seed_data()

    def _seed_data(self):
        self.stock["Club"]["Ice Buckets"] = 8
        self.stock["Club"]["Linens"] = 50
        self.stock["House"]["White Risers"] = 4
        self.stock["House"]["Orchids"] = 13

    def _reset_nicknames_if_new_day(self):
        today = date.today()
        if today != self.nickname_date:
            self.van_nicknames.clear()
            self.nickname_date = today

    def _valid_location(self, location):
        self._reset_nicknames_if_new_day()
        return location in WAREHOUSES or location in self.vans

    def list_vans(self):
        self._reset_nicknames_if_new_day()
        return self.vans[:]

    def van_label(self, van_name):
        nickname = self.van_nicknames.get(van_name)
        return f'{van_name} ("{nickname}")' if nickname else van_name

    def add_van(self):
        if not self.vans:
            next_number = 1
        else:
            numbers = [int(v.split("_")[1]) for v in self.vans if "_" in v and v.split("_")[1].isdigit()]
            next_number = (max(numbers) + 1) if numbers else (len(self.vans) + 1)

        new_van = f"Van_{next_number}"
        self.vans.append(new_van)
        return f"Added new van: {new_van}"

    def assign_van_nickname(self, van_name, nickname):
        self._reset_nicknames_if_new_day()
        if van_name not in self.vans:
            return f"Invalid van: {van_name}"

        cleaned = nickname.strip()
        if not cleaned:
            self.van_nicknames.pop(van_name, None)
            return f"Cleared nickname for {van_name}."

        self.van_nicknames[van_name] = cleaned
        return f'Assigned nickname "{cleaned}" to {van_name}.'

    def add_item(self, warehouse, item, qty):
        if warehouse not in WAREHOUSES:
            return f"Invalid warehouse: {warehouse}"
        if qty <= 0:
            return "Quantity must be greater than 0."
        self.stock[warehouse][item] += qty
        return f"Added {qty} {item} to {warehouse}."

    def transfer(self, from_location, to_location, item, qty):
        if not self._valid_location(from_location) or not self._valid_location(to_location):
            return "Invalid source or destination location."
        if qty <= 0:
            return "Quantity must be greater than 0."
        if self.stock[from_location][item] < qty:
            return f"Not enough {item} in {from_location}."

        self.stock[from_location][item] -= qty
        self.stock[to_location][item] += qty
        return f"Transferred {qty} {item} from {from_location} to {to_location}."

    def print_location_stock(self, location):
        if not self._valid_location(location):
            print("Invalid location.")
            return
        print(f"\nInventory at {location}:")
        items = self.stock[location]
        if not items or sum(items.values()) == 0:
            print("  (empty)")
            return
        for item, qty in sorted(items.items()):
            if qty > 0:
                print(f"  {item}: {qty}")

    def print_all_stock(self):
        print("\n=== Warehouses ===")
        for wh in WAREHOUSES:
            self.print_location_stock(wh)
        print("\n=== Vans ===")
        for van in self.vans:
            print(f"\n{self.van_label(van)}")
            self.print_location_stock(van)


def choose_location(prompt, allowed):
    print(prompt)
    print("Options:", ", ".join(allowed))
    choice = input("Enter location: ").strip()

    # Match user input without case sensitivity (e.g., club, CLUB, Club).
    allowed_map = {name.lower(): name for name in allowed}
    return allowed_map.get(choice.lower(), choice)


def choose_van(inv, prompt):
    vans = inv.list_vans()
    print(prompt)
    options_line = ", ".join(inv.van_label(van) for van in vans)
    print("Options:", options_line)
    choice = input("Enter van (e.g., Van_2): ").strip()

    allowed_map = {van.lower(): van for van in vans}
    return allowed_map.get(choice.lower(), choice)


def main():
    inv = InventorySystem()

    while True:
        print("\n=== Inventory Menu ===")
        print("1) View warehouse stock")
        print("2) View van stock")
        print("3) Add item to warehouse")
        print("4) Transfer warehouse -> van")
        print("5) Return van -> warehouse")
        print("6) View all stock")
        print("7) Add a new van")
        print("8) Assign/clear van nickname for today")
        print("9) Exit")

        choice = input("Choose an option: ").strip()

        if choice == "1":
            wh = choose_location("Select warehouse", WAREHOUSES)
            inv.print_location_stock(wh)

        elif choice == "2":
            van = choose_van(inv, "Select van")
            print(f"Selected: {inv.van_label(van)}")
            inv.print_location_stock(van)

        elif choice == "3":
            wh = choose_location("Select warehouse", WAREHOUSES)
            item = input("Item name: ").strip().title()
            qty = int(input("Quantity to add: ").strip())
            print(inv.add_item(wh, item, qty))

        elif choice == "4":
            wh = choose_location("From warehouse", WAREHOUSES)
            van = choose_van(inv, "To van")
            item = input("Item name: ").strip().title()
            qty = int(input("Quantity to transfer: ").strip())
            print(inv.transfer(wh, van, item, qty))

        elif choice == "5":
            van = choose_van(inv, "From van")
            wh = choose_location("To warehouse", WAREHOUSES)
            item = input("Item name: ").strip().title()
            qty = int(input("Quantity to return: ").strip())
            print(inv.transfer(van, wh, item, qty))

        elif choice == "6":
            inv.print_all_stock()

        elif choice == "7":
            print(inv.add_van())

        elif choice == "8":
            van = choose_van(inv, "Select van to nickname")
            nickname = input('Nickname/event for today (blank to clear): ').strip()
            print(inv.assign_van_nickname(van, nickname))

        elif choice == "9":
            print("Goodbye.")
            break

        else:
            print("Invalid choice. Enter 1-9.")


if __name__ == "__main__":
    main()