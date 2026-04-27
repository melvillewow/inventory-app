from datetime import datetime, timezone

import pandas as pd
import streamlit as st
from supabase import create_client

WAREHOUSES = ["Club", "House"]
DEFAULT_VANS = [f"Van_{i}" for i in range(1, 11)]
ALL_LOCATIONS = WAREHOUSES + DEFAULT_VANS

st.set_page_config(page_title="Inventory Tracker", layout="wide")


@st.cache_resource
def get_supabase():
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_ANON_KEY")
    if (not url or not key) and "secrets" in st.secrets:
        nested = st.secrets["secrets"]
        url = url or nested.get("SUPABASE_URL")
        key = key or nested.get("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def check_config():
    if get_supabase() is None:
        st.error("Missing Supabase secrets. Add SUPABASE_URL and SUPABASE_ANON_KEY.")
        st.code(
            "SUPABASE_URL='https://your-project.supabase.co'\n"
            "SUPABASE_ANON_KEY='your-anon-key'"
        )
        st.stop()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def initialize_van_state():
    today = datetime.now().date().isoformat()
    if "vans" not in st.session_state:
        st.session_state.vans = DEFAULT_VANS.copy()
    if "van_nicknames" not in st.session_state:
        st.session_state.van_nicknames = {}
    if st.session_state.get("van_nickname_date") != today:
        st.session_state.van_nickname_date = today
        st.session_state.van_nicknames = {}


def get_vans():
    initialize_van_state()
    return st.session_state.vans


def van_label(van_name):
    nickname = st.session_state.van_nicknames.get(van_name, "").strip()
    if nickname:
        return f'{van_name} ("{nickname}")'
    return van_name


def add_van():
    vans = get_vans()
    numbers = [int(v.split("_")[1]) for v in vans if "_" in v and v.split("_")[1].isdigit()]
    next_number = (max(numbers) + 1) if numbers else 1
    new_van = f"Van_{next_number}"
    vans.append(new_van)
    return new_van


def set_van_nickname(van_name, nickname):
    initialize_van_state()
    cleaned = nickname.strip()
    if cleaned:
        st.session_state.van_nicknames[van_name] = cleaned
    else:
        st.session_state.van_nicknames.pop(van_name, None)


def normalize_email(email):
    return email.strip().lower()


def get_user_role(sb, user_id):
    try:
        row = (
            sb.table("profiles")
            .select("role")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        return "staff"

    if row is None or getattr(row, "data", None) is None:
        return "staff"
    return row.data.get("role", "staff")


def login_screen(sb):
    st.title("Inventory Tracker")
    st.caption("Cloud inventory for warehouses and vans")
    left, right = st.columns(2)

    with left:
        st.subheader("Log In")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Log In", key="login_btn"):
            try:
                result = sb.auth.sign_in_with_password(
                    {"email": email.strip(), "password": password}
                )
                st.session_state.session = result.session
                st.session_state.user = result.user
                st.rerun()
            except Exception as exc:
                st.error(f"Login failed: {exc}")

    with right:
        st.subheader("Sign Up")
        su_email = st.text_input("Email ", key="signup_email")
        su_password = st.text_input("Password ", type="password", key="signup_password")
        if st.button("Create Account", key="signup_btn"):
            try:
                clean_email = normalize_email(su_email)
                if not clean_email:
                    st.error("Enter an email address.")
                    return
                allowed = sb.rpc(
                    "is_signup_email_allowed", {"p_email": clean_email}
                ).execute()
                if not allowed.data:
                    st.error("This email is not approved yet. Ask a manager for access.")
                    return
                sb.auth.sign_up(
                    {"email": clean_email, "password": su_password.strip()}
                )
                st.success("Account created. Now log in.")
            except Exception as exc:
                st.error(f"Sign up failed: {exc}")


def ensure_seed_data(sb):
    # Seeding can be blocked by RLS depending on role/policies.
    # If blocked, skip silently so the app stays usable.
    try:
        count_rows = sb.table("inventory").select("id", count="exact").limit(1).execute()
        total = count_rows.count or 0
        if total > 0:
            return
    except Exception:
        return

    starter = [
        ("Club", "Ice Buckets", 8),
        ("Club", "Linens", 50),
        ("House", "White Risers", 4),
        ("House", "Orchids", 13),
    ]
    for location, item, qty in starter:
        try:
            sb.rpc(
                "add_stock",
                {"p_location": location, "p_item": item, "p_qty": qty},
            ).execute()
        except Exception:
            # If user is not manager yet, add_stock may fail by design.
            pass


def list_inventory(sb):
    resp = sb.table("inventory").select("*").gt("qty", 0).order("location").execute()
    return resp.data or []


def list_history(sb):
    resp = sb.table("movements").select("*").order("created_at", desc=True).limit(200).execute()
    return resp.data or []


def get_qty(sb, location, item):
    row = (
        sb.table("inventory")
        .select("qty")
        .eq("location", location)
        .eq("item", item)
        .maybe_single()
        .execute()
    )
    if row.data is None:
        return 0
    return int(row.data["qty"])


def add_stock(sb, location, item, qty):
    result = sb.rpc(
        "add_stock",
        {"p_location": location, "p_item": item, "p_qty": int(qty)},
    ).execute()
    return result.data


def transfer(sb, from_loc, to_loc, item, qty):
    if qty <= 0:
        return False, "Quantity must be greater than 0."
    try:
        result = sb.rpc(
            "transfer_inventory",
            {
                "p_from_location": from_loc,
                "p_to_location": to_loc,
                "p_item": item,
                "p_qty": int(qty),
            },
        ).execute()
        message = result.data or f"Moved {qty} {item} from {from_loc} to {to_loc}."
        return True, message
    except Exception as exc:
        return False, str(exc)


def show_table_for_location(inventory_rows, location):
    rows = [
        {"Item": r["item"], "Qty": r["qty"]}
        for r in inventory_rows
        if r["location"] == location and int(r["qty"]) > 0
    ]
    if not rows:
        rows = [{"Item": "(empty)", "Qty": 0}]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def list_allowed_signups(sb):
    result = sb.rpc("list_signup_allowed_emails").execute()
    return result.data or []


def add_allowed_signup(sb, email):
    return sb.rpc("add_signup_allowed_email", {"p_email": normalize_email(email)}).execute()


def remove_allowed_signup(sb, email):
    return sb.rpc(
        "remove_signup_allowed_email", {"p_email": normalize_email(email)}
    ).execute()


def main_app(sb):
    initialize_van_state()
    vans = get_vans()
    role = get_user_role(sb, st.session_state.user.id)
    st.title("Inventory Tracker")
    st.caption("Manage stock across warehouses and vans.")
    st.write(f"Logged in as: `{st.session_state.user.email}`")
    st.write(f"Role: `{role}`")
    if st.button("Log Out"):
        sb.auth.sign_out()
        st.session_state.pop("session", None)
        st.session_state.pop("user", None)
        st.rerun()

    ensure_seed_data(sb)
    inventory_rows = list_inventory(sb)
    history_rows = list_history(sb)

    tab_names = [
        "View Inventory",
        "Add Stock",
        "Transfer / Return",
        "Movement History",
        "Van Assignments",
    ]
    if role == "manager":
        tab_names.append("User Access")
    tabs = st.tabs(tab_names)
    tab1, tab2, tab3, tab4, tab5 = tabs[0], tabs[1], tabs[2], tabs[3], tabs[4]

    with tab1:
        left, right = st.columns(2)
        with left:
            st.subheader("Warehouses")
            for wh in WAREHOUSES:
                st.markdown(f"**{wh}**")
                show_table_for_location(inventory_rows, wh)
        with right:
            st.subheader("Vans")
            selected_van = st.selectbox(
                "Choose van",
                vans,
                format_func=van_label,
            )
            st.markdown(f"**{van_label(selected_van)}**")
            show_table_for_location(inventory_rows, selected_van)

    with tab2:
        st.subheader("Add Stock to Warehouse")
        if role != "manager":
            st.info("Only managers can add warehouse stock.")
        else:
            add_wh = st.selectbox("Warehouse", WAREHOUSES, key="add_wh")
            add_item_name = st.text_input("Item name", key="add_item")
            add_qty = st.number_input("Quantity", min_value=1, step=1, key="add_qty")
            if st.button("Add Item", key="add_btn"):
                item = add_item_name.strip().title()
                if not item:
                    st.error("Enter an item name.")
                else:
                    try:
                        message = add_stock(sb, add_wh, item, int(add_qty))
                        st.success(message or f"Added {int(add_qty)} {item} to {add_wh}.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Add stock failed: {exc}")

    with tab3:
        st.subheader("Transfer Warehouse -> Van")
        c1, c2 = st.columns(2)
        with c1:
            from_wh = st.selectbox("From warehouse", WAREHOUSES, key="t_from_wh")
            wh_items = sorted(
                {r["item"] for r in inventory_rows if r["location"] == from_wh}
            )
            t_item = st.selectbox(
                "Item",
                wh_items if wh_items else ["(no items)"],
                key="t_item",
            )
            t_qty = st.number_input("Quantity", min_value=1, step=1, key="t_qty")
        with c2:
            to_van = st.selectbox("To van", vans, key="t_to_van", format_func=van_label)
            st.write("")
            st.write("")
            if st.button("Transfer to Van", key="transfer_btn"):
                if t_item == "(no items)":
                    st.error("Selected warehouse has no items.")
                else:
                    ok, message = transfer(
                        sb, from_wh, to_van, t_item, int(t_qty)
                    )
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

        st.divider()
        st.subheader("Return Van -> Warehouse")
        r1, r2 = st.columns(2)
        with r1:
            from_van = st.selectbox(
                "From van",
                vans,
                key="r_from_van",
                format_func=van_label,
            )
            van_items = sorted(
                {r["item"] for r in inventory_rows if r["location"] == from_van}
            )
            r_item = st.selectbox(
                "Item to return",
                van_items if van_items else ["(no items)"],
                key="r_item",
            )
            r_qty = st.number_input(
                "Quantity to return", min_value=1, step=1, key="r_qty"
            )
        with r2:
            to_wh = st.selectbox("Back to warehouse", WAREHOUSES, key="r_to_wh")
            st.write("")
            st.write("")
            if st.button("Return to Warehouse", key="return_btn"):
                if r_item == "(no items)":
                    st.error("Selected van has no items.")
                else:
                    ok, message = transfer(
                        sb, from_van, to_wh, r_item, int(r_qty)
                    )
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

    with tab4:
        st.subheader("Recent Movements")
        if not history_rows:
            st.info("No activity yet.")
        else:
            display = [
                {
                    "Time": r.get("created_at", ""),
                    "Action": r.get("action", ""),
                    "From": r.get("from_location", ""),
                    "To": r.get("to_location", ""),
                    "Item": r.get("item", ""),
                    "Qty": r.get("qty", 0),
                    "User": r.get("user_id", ""),
                }
                for r in history_rows
            ]
            st.dataframe(
                pd.DataFrame(display),
                use_container_width=True,
                hide_index=True,
            )

    with tab5:
        st.subheader("Van Naming and Daily Events")
        st.caption("Event nicknames reset automatically each new day.")

        if st.button("Add New Van", key="add_new_van_btn"):
            new_van = add_van()
            st.success(f"Added new van: {new_van}")
            st.rerun()

        st.write("")
        selected_nickname_van = st.selectbox(
            "Van to assign event nickname",
            vans,
            key="nickname_van",
            format_func=van_label,
        )
        nickname_value = st.text_input(
            "Nickname/event for today",
            key="nickname_value",
            placeholder='Example: loggerhead marine (leave blank to clear)',
        )
        if st.button("Save Nickname", key="save_nickname_btn"):
            set_van_nickname(selected_nickname_van, nickname_value)
            if nickname_value.strip():
                st.success(
                    f'Updated {selected_nickname_van} nickname to "{nickname_value.strip()}".'
                )
            else:
                st.success(f"Cleared nickname for {selected_nickname_van}.")
            st.rerun()

        st.write("")
        st.markdown("**Current van assignments for today**")
        assignments = [
            {
                "Van": van,
                "Event Nickname": st.session_state.van_nicknames.get(van, ""),
            }
            for van in vans
        ]
        st.dataframe(pd.DataFrame(assignments), use_container_width=True, hide_index=True)

    if role == "manager":
        with tabs[5]:
            st.subheader("Signup Allowlist")
            st.caption("Only emails in this list can create new accounts.")

            new_email = st.text_input("Allow email", key="allow_email")
            if st.button("Allow Email", key="allow_email_btn"):
                try:
                    add_allowed_signup(sb, new_email)
                    st.success(f"Allowed: {normalize_email(new_email)}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not allow email: {exc}")

            allowed_rows = list_allowed_signups(sb)
            if not allowed_rows:
                st.info("No approved signup emails yet.")
            else:
                emails = sorted({row.get("email", "") for row in allowed_rows if row.get("email")})
                selected = st.selectbox("Approved emails", emails, key="approved_email_pick")
                if st.button("Remove Selected Email", key="remove_email_btn"):
                    try:
                        remove_allowed_signup(sb, selected)
                        st.success(f"Removed: {selected}")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not remove email: {exc}")


def main():
    check_config()
    sb = get_supabase()
    if "session" not in st.session_state or st.session_state.session is None:
        login_screen(sb)
        return
    main_app(sb)


if __name__ == "__main__":
    main()