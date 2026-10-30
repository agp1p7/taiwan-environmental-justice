# 全臺環境正義 v0.1

狀態：可操作的資料匯入地圖原型，尚未內建、下載或驗證全國官方資料；不是已完成的全國分析成果。

## 使用
有網路的瀏覽器開啟 index.html。依序載入環境 CSV、村里 GeoJSON、標準化所得 CSV，切換圖層與縣市。CDN 和底圖需要網路；匯入資料不會上傳。未部署網站，未做瀏覽器端實際測試。

## 格式
- EMS_S_01 CSV：WGS84Lon/WGS84Lat、EmsNo、FacilityName、IsAir/IsWater/IsWaste。可讀取小寫欄位。CSV UTF-8 或 Big5。
- EMS_S_07 CSV：WGS84_LNG/WGS84_LAT、SITE_NAME。場址編碼異名需再核對實檔。
- 邊界：經緯度 GeoJSON FeatureCollection，保留 VILLCODE/COUNTYNAME/TOWNNAME/VILLNAME。官方 SHP 必須自行轉換。
- 所得：villcode,income_median,year；中位數千元、單年度、每村里一筆，代碼作文字保留前導零。原始所得檔若只有地名，必須先建立行政區對照後才可匯入；本版不做模糊配對。

## 來源
- https://data.moenv.gov.tw/dataset/detail/EMS_S_01
- https://data.moenv.gov.tw/dataset/detail/EMS_S_07
- https://data.gov.tw/dataset/7438
- https://data.gov.tw/dataset/103066

## 限制
未取得真實資料，不宣稱全國涵蓋率、座標有效率或所得配對率已驗證。列管表含歷史紀錄；本版不自動篩除解除列管，請於匯入前完成所需狀態篩選。設施彈窗保留原始欄位供核對。
座標範圍檢查只是粗篩，不代表已落在臺灣行政界。僅移除完全重複列，計數不是不重複事業數。類別可重疊，不可相加；廢棄物列管不等於處理廠；鄰近不等於暴露，空間關聯不等於因果。所得是綜所稅所得，不是完整可支配所得或貧窮率。未執行點落村里、距離分析、年份對照、API自動下載與全國效能測試。所得年度與邊界版本需人工核對。沒有內建假資料。
