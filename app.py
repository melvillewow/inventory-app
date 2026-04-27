from datetime import date, datetime, time, timezone

import pandas as pd
import streamlit as st
from supabase import create_client

WAREHOUSES = ["Club", "House"]
DEFAULT_VANS = [f"Van_{i}" for i in range(1, 11)]
REMOVAL_LOCATION = "__REMOVED__"

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


def ensure_seed_data(sb):
    try:
        count_rows = sb.table("inventory").select("id", count="exact").limit(1).execute()
        if (count_rows.count or 0) > 0:
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
        return True, (result.data or f"Moved {qty} {item} from {from_loc} to {to_loc}.")
    except Exception as exc:
        return False, str(exc)


def remove_stock(sb, warehouse, item, qty):
    if qty <= 0:
        return False, "Quantity must be greater than 0."
    current_qty = get_qty(sb, warehouse, item)
    if current_qty < qty:
        return False, f"Not enough {item} in {warehouse}. Available: {current_qty}."
    return transfer(sb, warehouse, REMOVAL_LOCATION, item, qty)


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
    return sb.rpc("remove_signup_allowed_email", {"p_email": normalize_email(email)}).execute()


def list_vans_from_inventory(inventory_rows):
    vans = sorted({r["location"] for r in inventory_rows if str(r["location"]).startswith("Van_")})
    return vans or DEFAULT_VANS.copy()


def list_events(sb):
    try:
        resp = sb.table("events").select("*").order("event_date").order("start_time").execute()
        return resp.data or []
    except Exception:
        return []


def list_event_vans(sb, event_id):
    resp = sb.table("event_vans").select("*").eq("event_id", event_id).order("van_name").execute()
    return resp.data or []


def list_packup_items(sb, event_van_id):
    resp = sb.table("packup_items").select("*").eq("event_van_id", event_van_id).order("item").execute()
    return resp.data or []


def safe_dt(event_row):
    return datetime.combine(
        date.fromisoformat(event_row["event_date"]),
        time.fromisoformat(event_row["start_time"]),
    ), datetime.combine(
        date.fromisoformat(event_row["event_date"]),
        time.fromisoformat(event_row["end_time"]),
    )


def event_is_active(event_row, current_local):
    start_dt, end_dt = safe_dt(event_row)
    return start_dt <= current_local <= end_dt


def sync_ended_nicknames(sb):
    now_utc = now_iso()
    events = list_events(sb)
    past_event_ids = []
    now_local = datetime.now()
    for event_row in events:
        _, end_dt = safe_dt(event_row)
        if end_dt < now_local:
            past_event_ids.append(event_row["id"])
    if not past_event_ids:
        return
    try:
        sb.table("van_nickname_history").update({"cleared_at": now_utc}).is_("cleared_at", "null").in_("event_id", past_event_ids).execute()
    except Exception:
        pass


def active_nickname_map(sb):
    now_local = datetime.now()
    events = list_events(sb)
    active_events = [event_row for event_row in events if event_is_active(event_row, now_local)]
    nicknames = {}
    for event_row in active_events:
        for ev in list_event_vans(sb, event_row["id"]):
            nicknames[ev["van_name"]] = ev["nickname"]
    return nicknames


def format_van_name(van_name, nickname_map):
    nickname = nickname_map.get(van_name, "").strip()
    return f'{van_name} ("{nickname}")' if nickname else van_name


def create_event_with_vans(sb, title, event_date, start_time, end_time, vans):
    created = (
        sb.table("events")
        .insert(
            {
                "title": title.strip(),
                "event_date": str(event_date),
                "start_time": str(start_time),
                "end_time": str(end_time),
                "status": "planned",
                "created_by": st.session_state.user.id,
            }
        )
        .execute()
    )
    event_id = created.data[0]["id"]
    if not vans:
        return event_id
    rows = [{"event_id": event_id, "van_name": van, "nickname": title.strip()} for van in vans]
    sb.table("event_vans").insert(rows).execute()
    history_rows = [{"event_id": event_id, "van_name": van, "nickname": title.strip()} for van in vans]
    sb.table("van_nickname_history").insert(history_rows).execute()
    return event_id


def add_or_update_packup_item(sb, event_van_id, item, planned_qty):
    rows = list_packup_items(sb, event_van_id)
    existing = next((r for r in rows if r["item"].lower() == item.lower()), None)
    if existing:
        sb.table("packup_items").update({"planned_qty": int(planned_qty)}).eq("id", existing["id"]).execute()
    else:
        sb.table("packup_items").insert({"event_van_id": event_van_id, "item": item, "planned_qty": int(planned_qty), "checked_qty": 0}).execute()


def inventory_gap_for_date(inventory_rows, events, event_vans_map, packup_map, selected_date):
    inventory_by_item = {}
    for row in inventory_rows:
        if row["location"] in WAREHOUSES:
            inventory_by_item[row["item"]] = inventory_by_item.get(row["item"], 0) + int(row["qty"])

    planned_by_item = {}
    for event_row in events:
        if event_row["event_date"] != str(selected_date):
            continue
        for ev in event_vans_map.get(event_row["id"], []):
            for item_row in packup_map.get(ev["id"], []):
                planned_by_item[item_row["item"]] = planned_by_item.get(item_row["item"], 0) + int(item_row["planned_qty"])

    items = sorted(set(inventory_by_item.keys()) | set(planned_by_item.keys()))
    return [
        {
            "Item": item,
            "Warehouse Stock": inventory_by_item.get(item, 0),
            "Planned Need": planned_by_item.get(item, 0),
            "Shortage": max(0, planned_by_item.get(item, 0) - inventory_by_item.get(item, 0)),
        }
        for item in items
    ]


def compute_van_status(event_row, items):
    now_local = datetime.now()
    start_dt, _ = safe_dt(event_row)
    remaining = int((start_dt - now_local).total_seconds() // 60)
    fully_packed = all(int(i["checked_qty"]) >= int(i["planned_qty"]) for i in items) if items else False

    if fully_packed:
        return "Green", "Packed"
    if remaining <= 60:
        return "Red", f"Late by {-remaining}m" if remaining < 0 else f"{remaining}m left"
    return "Yellow", f"{remaining // 60}h {remaining % 60}m left"


def render_event_detail(sb, event_row, event_vans, packup_map, editable_checklist):
    st.markdown(f"### {event_row['title']}")
    st.caption(f"{event_row['event_date']} | {event_row['start_time']} - {event_row['end_time']}")
    for ev in event_vans:
        items = packup_map.get(ev["id"], [])
        status_color, status_text = compute_van_status(event_row, items)
        st.markdown(f"**{ev['van_name']}** ({ev['nickname']})  \nStatus: `{status_color}` - {status_text}")
        if not items:
            st.info("No items planned for this van yet.")
            continue
        rows = []
        for row in items:
            rows.append(
                {
                    "Item": row["item"],
                    "Planned": row["planned_qty"],
                    "Checked": row["checked_qty"],
                    "Done": int(row["checked_qty"]) >= int(row["planned_qty"]),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if editable_checklist:
            item_names = [r["item"] for r in items]
            selected_item = st.selectbox(f"Update check-off for {ev['van_name']}", item_names, key=f"sel_{ev['id']}")
            selected_row = next(r for r in items if r["item"] == selected_item)
            new_checked = st.number_input(
                "Checked qty",
                min_value=0,
                max_value=int(selected_row["planned_qty"]),
                value=int(selected_row["checked_qty"]),
                step=1,
                key=f"chk_{ev['id']}_{selected_item}",
            )
            if st.button("Save Check-Off", key=f"save_chk_{ev['id']}_{selected_item}"):
                sb.table("packup_items").update(
                    {
                        "checked_qty": int(new_checked),
                        "checked_at": now_iso(),
                        "checked_by": st.session_state.user.id,
                    }
                ).eq("id", selected_row["id"]).execute()
                st.success("Checklist updated.")
                st.rerun()


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
                result = sb.auth.sign_in_with_password({"email": email.strip(), "password": password})
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
                allowed = sb.rpc("is_signup_email_allowed", {"p_email": clean_email}).execute()
                if not allowed.data:
                    st.error("This email is not approved yet. Ask a manager for access.")
                    return
                sb.auth.sign_up({"email": clean_email, "password": su_password.strip()})
                st.success("Account created. Now log in.")
            except Exception as exc:
                st.error(f"Sign up failed: {exc}")


def main_app(sb):
    role = get_user_role(sb, st.session_state.user.id)
    st.title("Inventory Tracker")
    st.caption("Manage stock, events, and van packup.")
    st.write(f"Logged in as: `{st.session_state.user.email}`")
    st.write(f"Role: `{role}`")
    if st.button("Log Out"):
        sb.auth.sign_out()
        st.session_state.pop("session", None)
        st.session_state.pop("user", None)
        st.rerun()

    ensure_seed_data(sb)
    sync_ended_nicknames(sb)

    inventory_rows = list_inventory(sb)
    history_rows = list_history(sb)
    vans = list_vans_from_inventory(inventory_rows)
    events = list_events(sb)
    event_vans_map = {e["id"]: list_event_vans(sb, e["id"]) for e in events}
    packup_map = {}
    for event_vans in event_vans_map.values():
        for ev in event_vans:
            packup_map[ev["id"]] = list_packup_items(sb, ev["id"])
    nickname_map = active_nickname_map(sb)

    tab_names = ["View Inventory", "Events Calendar", "Today Packup", "Transfer / Return", "Movement History"]
    if role == "manager":
        tab_names += ["Plan Events", "Inventory Sufficiency", "Add / Remove Stock", "User Access"]
    tabs = st.tabs(tab_names)
    tab_by_name = dict(zip(tab_names, tabs))

    with tab_by_name["View Inventory"]:
        left, right = st.columns(2)
        with left:
            st.subheader("Warehouses")
            for wh in WAREHOUSES:
                st.markdown(f"**{wh}**")
                show_table_for_location(inventory_rows, wh)
        with right:
            st.subheader("Vans")
            selected_van = st.selectbox("Choose van", vans, format_func=lambda v: format_van_name(v, nickname_map))
            st.markdown(f"**{format_van_name(selected_van, nickname_map)}**")
            show_table_for_location(inventory_rows, selected_van)

    with tab_by_name["Events Calendar"]:
        st.subheader("Events Calendar")
        if not events:
            st.info("No events yet. Managers can create events in Plan Events.")
        else:
            grouped = {}
            for ev in events:
                grouped.setdefault(ev["event_date"], []).append(ev)
            selected_day = st.selectbox("Choose day", sorted(grouped.keys()))
            day_events = grouped[selected_day]
            st.markdown("### Event Titles")
            for ev in day_events:
                if st.button(f"{ev['start_time']} - {ev['title']}", key=f"open_evt_{ev['id']}"):
                    st.session_state.selected_event_id = ev["id"]
            event_id = st.session_state.get("selected_event_id")
            if event_id:
                selected_event = next((ev for ev in events if ev["id"] == event_id), None)
                if selected_event and selected_event["event_date"] == selected_day:
                    render_event_detail(sb, selected_event, event_vans_map.get(event_id, []), packup_map, editable_checklist=False)

    with tab_by_name["Today Packup"]:
        st.subheader("Today Packup")
        today = str(date.today())
        today_events = [ev for ev in events if ev["event_date"] == today]
        if not today_events:
            st.info("No events scheduled for today.")
        else:
            rows = []
            for ev in today_events:
                for evan in event_vans_map.get(ev["id"], []):
                    items = packup_map.get(evan["id"], [])
                    color, detail = compute_van_status(ev, items)
                    rows.append({"event": ev, "event_van": evan, "color": color, "detail": detail})
            rows.sort(key=lambda r: {"Red": 0, "Yellow": 1, "Green": 2}.get(r["color"], 3))
            for row in rows:
                st.markdown(
                    f"**{row['event']['title']} | {row['event_van']['van_name']}** - "
                    f"`{row['color']}` ({row['detail']})"
                )
                render_event_detail(
                    sb,
                    row["event"],
                    [row["event_van"]],
                    packup_map,
                    editable_checklist=True,
                )
                st.divider()

    with tab_by_name["Transfer / Return"]:
        st.subheader("Transfer Warehouse -> Van")
        c1, c2 = st.columns(2)
        with c1:
            from_wh = st.selectbox("From warehouse", WAREHOUSES, key="t_from_wh")
            wh_items = sorted({r["item"] for r in inventory_rows if r["location"] == from_wh})
            t_item = st.selectbox("Item", wh_items if wh_items else ["(no items)"], key="t_item")
            t_qty = st.number_input("Quantity", min_value=1, step=1, key="t_qty")
        with c2:
            to_van = st.selectbox("To van", vans, key="t_to_van", format_func=lambda v: format_van_name(v, nickname_map))
            if st.button("Transfer to Van", key="transfer_btn"):
                if t_item == "(no items)":
                    st.error("Selected warehouse has no items.")
                else:
                    ok, message = transfer(sb, from_wh, to_van, t_item, int(t_qty))
                    (st.success if ok else st.error)(message)
                    if ok:
                        st.rerun()

        st.divider()
        st.subheader("Return Van -> Warehouse")
        r1, r2 = st.columns(2)
        with r1:
            from_van = st.selectbox("From van", vans, key="r_from_van", format_func=lambda v: format_van_name(v, nickname_map))
            van_items = sorted({r["item"] for r in inventory_rows if r["location"] == from_van})
            r_item = st.selectbox("Item to return", van_items if van_items else ["(no items)"], key="r_item")
            r_qty = st.number_input("Quantity to return", min_value=1, step=1, key="r_qty")
        with r2:
            to_wh = st.selectbox("Back to warehouse", WAREHOUSES, key="r_to_wh")
            if st.button("Return to Warehouse", key="return_btn"):
                if r_item == "(no items)":
                    st.error("Selected van has no items.")
                else:
                    ok, message = transfer(sb, from_van, to_wh, r_item, int(r_qty))
                    (st.success if ok else st.error)(message)
                    if ok:
                        st.rerun()

    with tab_by_name["Movement History"]:
        st.subheader("Recent Movements")
        if not history_rows:
            st.info("No activity yet.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
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
                ),
                use_container_width=True,
                hide_index=True,
            )

    if role == "manager":
        with tab_by_name["Plan Events"]:
            st.subheader("Plan Events")
            title = st.text_input("Event title", key="plan_event_title")
            event_day = st.date_input("Event day", key="plan_event_day")
            c1, c2 = st.columns(2)
            with c1:
                start_t = st.time_input("Start time", key="plan_start_t")
            with c2:
                end_t = st.time_input("End time", value=time(23, 0), key="plan_end_t")
            vans_for_event = st.multiselect("Assign vans", vans, key="plan_vans")
            if st.button("Create Event", key="create_event_btn"):
                if not title.strip():
                    st.error("Event title is required.")
                elif start_t >= end_t:
                    st.error("End time must be after start time.")
                elif not vans_for_event:
                    st.error("Select at least one van.")
                else:
                    try:
                        created_event_id = create_event_with_vans(sb, title, event_day, start_t, end_t, vans_for_event)
                        st.success("Event created.")
                        st.session_state.manage_event_id = created_event_id
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not create event: {exc}")

            manager_events = list_events(sb)
            if manager_events:
                event_pick = st.selectbox(
                    "Select event to edit packup lists",
                    manager_events,
                    format_func=lambda e: f"{e['event_date']} | {e['title']}",
                    key="manage_event_pick",
                )
                event_vans = list_event_vans(sb, event_pick["id"])
                if event_vans:
                    evan_pick = st.selectbox(
                        "Van list to edit",
                        event_vans,
                        format_func=lambda evan: f"{evan['van_name']} ({evan['nickname']})",
                        key="manage_event_van_pick",
                    )
                    p_item = st.text_input("Packup item", key="packup_item_name").strip().title()
                    p_qty = st.number_input("Planned qty", min_value=1, step=1, key="packup_item_qty")
                    if st.button("Add/Update Packup Item", key="add_packup_item_btn"):
                        if not p_item:
                            st.error("Enter an item name.")
                        else:
                            try:
                                add_or_update_packup_item(sb, evan_pick["id"], p_item, int(p_qty))
                                st.success("Packup list updated.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Could not update packup list: {exc}")

        with tab_by_name["Inventory Sufficiency"]:
            st.subheader("Inventory Sufficiency")
            selected_day = st.date_input("Date to analyze", value=date.today(), key="sufficiency_day")
            gap_rows = inventory_gap_for_date(inventory_rows, events, event_vans_map, packup_map, selected_day)
            if not gap_rows:
                st.info("No inventory or planned items for this date.")
            else:
                gap_df = pd.DataFrame(gap_rows)
                st.dataframe(gap_df, use_container_width=True, hide_index=True)
                shortage_rows = [r for r in gap_rows if r["Shortage"] > 0]
                if shortage_rows:
                    st.error("Some items are short for planned events on this date.")
                else:
                    st.success("Inventory is sufficient for all planned event items on this date.")

        with tab_by_name["Add / Remove Stock"]:
            st.subheader("Add Stock to Warehouse")
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

            st.divider()
            st.subheader("Remove Stock from Warehouse")
            remove_wh = st.selectbox("Warehouse to remove from", WAREHOUSES, key="remove_wh")
            remove_items = sorted({r["item"] for r in inventory_rows if r["location"] == remove_wh})
            remove_item = st.selectbox("Item to remove", remove_items if remove_items else ["(no items)"], key="remove_item")
            remove_qty = st.number_input("Quantity to remove", min_value=1, step=1, key="remove_qty")
            if st.button("Remove Item", key="remove_btn"):
                if remove_item == "(no items)":
                    st.error("Selected warehouse has no items.")
                else:
                    ok, message = remove_stock(sb, remove_wh, remove_item, int(remove_qty))
                    (st.success if ok else st.error)(message if not ok else f"Removed {int(remove_qty)} {remove_item} from {remove_wh}.")
                    if ok:
                        st.rerun()

        with tab_by_name["User Access"]:
            st.subheader("Signup Allowlist")
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