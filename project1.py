from collections import defaultdict


WAREHOUSES = ["Club", "House"]
VANS = [f"VAN{i}" for i in range(1, 11)]


class InventorySystem:
    def __init__(self):
        # location -> item -> quantity
        self.stock = defaultdict(lambda: defaultdict(int))
        self._seed_data()

    def _seed_data(self):
        self.stock["Club"]["Ice Buckets"] = 8
        self.stock["Club"]["Linens"] = 50
        self.stock["House"]["White Risers"] = 4
        self.stock["House"]["Orchids"] = 13

    def _valid_location(self, location):
        return location in WAREHOUSES or location in VANS

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
        for van in VANS:
            self.print_location_stock(van)


def choose_location(prompt, allowed):
    print(prompt)
    print("Options:", ", ".join(allowed))
    choice = input("Enter location: ").strip()

    # Match user input without case sensitivity (e.g., club, CLUB, Club).
    allowed_map = {name.lower(): name for name in allowed}
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
        print("7) Exit")

        choice = input("Choose an option: ").strip()

        if choice == "1":
            wh = choose_location("Select warehouse", WAREHOUSES)
            inv.print_location_stock(wh)

        elif choice == "2":
            van = choose_location("Select van", VANS)
            inv.print_location_stock(van)

        elif choice == "3":
            wh = choose_location("Select warehouse", WAREHOUSES)
            item = input("Item name: ").strip().title()
            qty = int(input("Quantity to add: ").strip())
            print(inv.add_item(wh, item, qty))

        elif choice == "4":
            wh = choose_location("From warehouse", WAREHOUSES)
            van = choose_location("To van", VANS)
            item = input("Item name: ").strip().title()
            qty = int(input("Quantity to transfer: ").strip())
            print(inv.transfer(wh, van, item, qty))

        elif choice == "5":
            van = choose_location("From van", VANS)
            wh = choose_location("To warehouse", WAREHOUSES)
            item = input("Item name: ").strip().title()
            qty = int(input("Quantity to return: ").strip())
            print(inv.transfer(van, wh, item, qty))

        elif choice == "6":
            inv.print_all_stock()

        elif choice == "7":
            print("Goodbye.")
            break

        else:
            print("Invalid choice. Enter 1-7.")


if __name__ == "__main__":
    main()