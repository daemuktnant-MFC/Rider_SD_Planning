import streamlit as st
import pandas as pd
import numpy as np
import folium
from streamlit_folium import st_folium
import math
from datetime import timedelta, datetime
import os # เพิ่มการ import os เพื่อใช้ os.path.splitext
import re

# ตั้งค่า layout ให้เต็มหน้าจอ
st.set_page_config(layout="wide")

st.title("แผนที่และเส้นทางวิ่ง Rider")

# --- ส่วนของการอัปโหลดไฟล์ (รองรับหลายประเภท) ---
uploaded_file = st.sidebar.file_uploader("อัปโหลดไฟล์ข้อมูลของคุณ (Excel: .xlsx, .xlsm, .xlsb | ข้อความ: .csv, .txt)", type=["xlsx", "xlsm", "xlsb", "csv", "txt"])

df_raw = None # กำหนด df_raw เป็น None เริ่มต้น

# ฟังก์ชันสำหรับประมวลผล Time Check Status
def parse_time_check(value):
    # Handle NaN/None explicitly first
    if pd.isna(value):
        return 'not_yet'

    # Check if it's already a datetime object (e.g., if loaded directly from excel as time)
    if isinstance(value, (datetime, pd.Timestamp, pd.Timedelta)):
        return 'checked'

    value_str = str(value).strip().lower()

    if value_str == 'pending':
        return 'pending'

    try:
        # ลองหลายรูปแบบของเวลา
        dt_obj = pd.to_datetime(value, format='%H:%M:%S', errors='coerce')
        if pd.isna(dt_obj):
            dt_obj = pd.to_datetime(value, format='%H:%M', errors='coerce')
        if pd.isna(dt_obj):
            dt_obj = pd.to_datetime(value, errors='coerce') # ลองแบบทั่วไป
        if pd.isna(dt_obj):
            return 'not_yet' # ถ้าแปลงไม่ได้ให้เป็น 'not_yet'
        return 'checked' # ถ้าแปลงได้ให้เป็น 'checked'
    except Exception:
        return 'not_yet' # ถ้ามีข้อผิดพลาดอื่นๆ ก็เป็น 'not_yet'

# ฟังก์ชันสำหรับการโหลดและประมวลผลข้อมูลเบื้องต้น (ใช้ Cache และรองรับหลายประเภทไฟล์)
@st.cache_data(ttl=600)
def load_and_preprocess_data(file_uploader_object):
    if file_uploader_object is None:
        return None

    df_temp = None
    file_extension = os.path.splitext(file_uploader_object.name)[1].lower()

    if file_extension in [".xlsx", ".xlsm"]:
        try:
            df_temp = pd.read_excel(file_uploader_object, sheet_name="Data", engine="openpyxl")
            st.success(f"อ่านไฟล์ Excel ({file_extension}) สำเร็จ!")
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์ Excel ({file_extension}): {e}")
            return None
    elif file_extension == ".xlsb":
        try:
            # Requires 'pyxlsb' to be installed: pip install pyxlsb
            df_temp = pd.read_excel(file_uploader_object, sheet_name="Data", engine="pyxlsb")
            st.success(f"อ่านไฟล์ Excel Binary ({file_extension}) สำเร็จ!")
        except ImportError:
            st.error("❗ โปรดติดตั้งไลบรารี 'pyxlsb' โดยรันคำสั่ง: `pip install pyxlsb` เพื่อรองรับไฟล์ .xlsb")
            return None
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์ Excel Binary ({file_extension}): {e}")
            return None
    elif file_extension in [".csv", ".txt"]:
        encodings_to_try = ['utf-8', 'tis-620', 'cp1252', 'latin1']
        for encoding in encodings_to_try:
            file_uploader_object.seek(0) # รีเซ็ต pointer ของไฟล์ก่อนลองอ่านแต่ละครั้ง
            try:
                df_temp = pd.read_csv(file_uploader_object, encoding=encoding)
                st.success(f"อ่านไฟล์ข้อความ ({file_extension}) ด้วย encoding '{encoding}' สำเร็จ")
                break # ออกจาก loop ถ้าอ่านสำเร็จ
            except UnicodeDecodeError:
                continue # ลอง encoding ถัดไป
            except Exception as e:
                st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์ข้อความ ({file_extension}) ด้วย encoding '{encoding}': {e}")
                return None
        if df_temp is None:
            st.error(f"ไม่สามารถอ่านไฟล์ข้อความ ({file_extension}) ด้วย encoding ที่พยายามทั้งหมดได้ กรุณาลองตรวจสอบ encoding ของไฟล์ต้นฉบับ")
            return None
    else:
        st.error(f"⚠️ รูปแบบไฟล์ '{file_extension}' ไม่รองรับ กรุณาอัปโหลดไฟล์ในรูปแบบ .xlsx, .xlsm, .xlsb, .csv, หรือ .txt")
        return None

    # --- ส่วนตรวจสอบคอลัมน์ที่จำเป็น ---
    required_columns = ["Order ID", "LAT", "LON", "SLA STS", "Rider Name", "Time Check", "DP Time", "SLA"]
    missing_columns = [col for col in required_columns if col not in df_temp.columns]

    if missing_columns:
        st.error(f"คอลัมน์ที่จำเป็นไม่ครบถ้วนในไฟล์ที่อัปโหลด: {', '.join(missing_columns)}")
        return None # คืนค่า None เพื่อหยุดการประมวลผลต่อ

    # --- การประมวลผลข้อมูล ---
    merged_df_processed = df_temp.copy()
    merged_df_processed["LAT"] = pd.to_numeric(merged_df_processed["LAT"], errors="coerce")
    merged_df_processed["LON"] = pd.to_numeric(merged_df_processed["LON"], errors="coerce")
    merged_df_processed.dropna(subset=["LAT", "LON"], inplace=True)

    # แปลงคอลัมน์ DP Time และ SLA
    for col_name in ['DP Time', 'SLA']:
        # ตรวจสอบว่าคอลัมน์มีอยู่จริงใน DataFrame ก่อนประมวลผล
        if col_name in merged_df_processed.columns:
            if pd.api.types.is_numeric_dtype(merged_df_processed[col_name]):
                merged_df_processed[f'{col_name}_for_sort'] = pd.to_datetime(merged_df_processed[col_name], unit='d', origin='1899-12-30', errors='coerce')
            else:
                merged_df_processed[f'{col_name}_for_sort'] = pd.to_datetime(merged_df_processed[col_name], errors='coerce', format='%H:%M:%S')
                merged_df_processed[f'{col_name}_for_sort'] = merged_df_processed[f'{col_name}_for_sort'].fillna(
                    pd.to_datetime(merged_df_processed[col_name], errors='coerce', format='%H:%M')
                )
            merged_df_processed[col_name] = merged_df_processed[f'{col_name}_for_sort'].dt.strftime('%H:%M').fillna('')
            merged_df_processed = merged_df_processed.drop(columns=[f'{col_name}_for_sort'])
        else:
            merged_df_processed[col_name] = '' # สร้างคอลัมน์ว่างๆ ถ้าไม่มีใน CSV ต้นฉบับ


    # ใช้ฟังก์ชัน parse_time_check
    merged_df_processed["Time Check Status"] = merged_df_processed["Time Check"].apply(parse_time_check)
    merged_df_processed["Rider Name"] = merged_df_processed["Rider Name"].astype(str).str.strip()

    # ค่าพิกัด MFC
    center_lat = 13.737929161400837
    center_lon = 100.63687556823479

    # คำนวณ bearing
    def fast_bearing(lat2, lon2):
        dLon = np.radians(lon2 - center_lon)
        lat1 = np.radians(center_lat)
        lat2 = np.radians(lat2)
        y = np.sin(dLon) * np.cos(lat2)
        x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dLon)
        bearing = np.degrees(np.arctan2(y, x))
        return (bearing + 360) % 360

    merged_df_processed["Bearing"] = fast_bearing(merged_df_processed["LAT"], merged_df_processed["LON"])

    def assign_zone(bearing):
        if 0 <= bearing < 90: return "Zone 4"
        elif 90 <= bearing < 180: return "Zone 3"
        elif 180 <= bearing < 270: return "Zone 2"
        else: return "Zone 1"

    merged_df_processed["Zone"] = merged_df_processed["Bearing"].apply(assign_zone)

    return merged_df_processed, center_lat, center_lon # ส่งคืนข้อมูลที่ประมวลผลแล้วและพิกัดศูนย์กลาง

# เรียกใช้ฟังก์ชันที่ถูก Cache
processed_data_tuple = load_and_preprocess_data(uploaded_file)

if processed_data_tuple is not None:
    merged_df, center_lat, center_lon = processed_data_tuple
    st.success("อัปโหลดไฟล์และประมวลผลข้อมูลเบื้องต้นสำเร็จ!")

    # --- ตัวเลือกการกรอง ---
    st.sidebar.header("ตัวเลือกการกรอง")
    filtered_df = merged_df.copy()

    # Filter by Order ID
    order_options = sorted(filtered_df["Order ID"].unique())
    selected_orders = st.sidebar.multiselect("เลือก Order ID:", order_options)
    if selected_orders:
        filtered_df = filtered_df[filtered_df["Order ID"].isin(selected_orders)]

    # Filter by Rider Name
    rider_options = sorted(filtered_df["Rider Name"].unique())
    selected_riders = st.sidebar.multiselect("เลือก Rider Name:", rider_options)
    if selected_riders:
        filtered_df = filtered_df[filtered_df["Rider Name"].isin(selected_riders)]

    # Filter by Time Check (ใช้ค่าดิบจากคอลัมน์ "Time Check" ในการกรอง)
    time_check_options = sorted(filtered_df["Time Check"].astype(str).unique().tolist())
    selected_time_checks_raw = st.sidebar.multiselect("เลือก Time Check:", time_check_options)
    if selected_time_checks_raw:
        filtered_df = filtered_df[filtered_df["Time Check"].astype(str).isin(selected_time_checks_raw)]

    # Filter by Zone
    zone_options = sorted(filtered_df["Zone"].unique())
    selected_zones = st.sidebar.multiselect("เลือก Zone:", zone_options)
    if selected_zones:
        filtered_df = filtered_df[filtered_df["Zone"].isin(selected_zones)]


    # --- การเรียงลำดับข้อมูล ---
    # ตรวจสอบว่าคอลัมน์ 'SLA_for_sort' มีอยู่จริง
    # ควรตรวจสอบใน merged_df เพราะ filtered_df อาจว่างเปล่า
    if "SLA_for_sort" in merged_df.columns:
        filtered_df = filtered_df.sort_values(by=["SLA_for_sort", "Order ID"], ascending=[True, True])
    else:
        filtered_df = filtered_df.sort_values(by="Order ID", ascending=True)

    # --- แสดง Distribution of Time Check Status ใน Filtered Data ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("สถานะ Time Check ของข้อมูลที่ถูกกรอง:")
    if not filtered_df.empty:
        status_counts = filtered_df["Time Check Status"].value_counts()
        for status, count in status_counts.items():
            st.sidebar.write(f"- {status.capitalize()}: {count} orders")
    else:
        st.sidebar.write("ไม่มีข้อมูลหลังจากกรอง")
    st.sidebar.markdown("---")


    # --- ส่วนสร้างลิงก์ Google Maps ---
    if not filtered_df.empty:
        # ใช้ .copy() เพื่อป้องกัน SettingWithCopyWarning
        unique_coords_df = filtered_df.groupby(["LAT", "LON"]).size().reset_index()[["LAT", "LON"]].copy()
        destination_coords = [f"{row['LAT']},{row['LON']}" for _, row in unique_coords_df.iterrows()]

        if len(destination_coords) > 11:
            st.warning("⚠️ มีจุดหมายปลายทางมากกว่า 11 จุด จะแสดงเส้นทางสำหรับ 11 จุดแรกเท่านั้น")
            destination_coords = destination_coords[:11]

        if destination_coords:
            origin_param = f"{center_lat},{center_lon}"
            path_coords = [origin_param] + destination_coords
            # ใช้ URL ที่เป็นทางการของ Google Maps สำหรับเส้นทาง
            maps_url = f"https://www.google.com/maps/dir/{'/'.join(path_coords)}?travelmode=driving"

            st.markdown(f"**📍 [คลิกเพื่อดูเส้นทางทั้งหมดใน Google Maps]({maps_url})**")
    else:
        st.info("ไม่มีข้อมูล Order ที่เลือกเพื่อสร้างเส้นทาง")

    # --- การสร้างแผนที่ ---
    m = folium.Map(location=[center_lat, center_lon], zoom_start=14)
    folium.Marker(location=[center_lat, center_lon], popup="📍MFC", icon=folium.Icon(color="green", icon="star")).add_to(m)
    folium.Circle(location=[center_lat, center_lon], radius=4000, color='blue', opacity=0.4, fill=True, fill_color='red', fill_opacity=0.05, popup="รัศมี 4 กม.").add_to(m)

    # กำหนดสีสำหรับ Zone
    zone_colors = {"Zone 1": "red", "Zone 2": "orange", "Zone 3": "purple", "Zone 4": "blue"}

    # จัดกลุ่มข้อมูลสำหรับแสดงผลบนหมุด
    grouped = filtered_df.groupby(["LAT", "LON"]).agg(
        order_ids=('Order ID', lambda x: ", ".join(sorted(set(map(str, x))))),
        rider_names=('Rider Name', lambda x: ", ".join(sorted(set(map(str, x))))),
        dp_times=('DP Time', lambda x: ", ".join(sorted(filter(None, x)))),
        sla_times=('SLA', lambda x: ", ".join(sorted(filter(None, x)))),
        zone=('Zone', 'first'),
    ).reset_index()

    # สร้าง Popup Text และกำหนดสีสำหรับหมุด
    for idx, row in grouped.iterrows():
        popup_html = f"""
        <b>Order:</b> {row['order_ids']}<br>
        <b>Rider:</b> {row['rider_names']}<br>
        <b>DP Time:</b> {row['dp_times'] if row['dp_times'] else 'N/A'}<br>
        <b>SLA:</b> {row['sla_times'] if row['sla_times'] else 'N/A'}<br>
        <b>Zone:</b> {row['zone']}<br>
        """

        # กำหนดสีหมุดแยกตาม Rider Zone
        marker_color = zone_colors.get(row['zone'], 'blue')


        folium.Marker(
            location=[row["LAT"], row["LON"]],
            popup=popup_html,
            icon=folium.Icon(color=marker_color, icon="info-sign")
        ).add_to(m)

    # วาดเส้นทางตามโซน
    #for zone, color in zone_colors.items():
        #zone_points_df = filtered_df[filtered_df["Zone"] == zone]
        #if not zone_points_df.empty:
            #route_points = [[center_lat, center_lon]] + zone_points_df[["LAT", "LON"]].values.tolist()
            #folium.PolyLine(route_points, color=color, weight=2.5, opacity=0.8, popup=zone).add_to(m)

    st_folium(m, width="100%", height=900)

    # --- แสดงตารางข้อมูล ---
    columns_to_display = ["Order ID", "SLA", "Rider Name", "SLA STS", "Time Check", "Time Check Status", "Zone", "DP Time"]
    st.dataframe(filtered_df[columns_to_display], use_container_width=True)
else:
    st.info("กรุณาอัปโหลดไฟล์ข้อมูล (Excel หรือข้อความ) เพื่อเริ่มต้น")
