# 全臺環境正義：資料審閱預覽與匯入原型

目前已發布可操作的所得與環境資料審閱預覽；不是已完成的全臺環境正義分析，也不是現行污染、違法或曝險判定。

## 網站入口

- [已內建資料的地圖預覽](https://agp1p7.github.io/taiwan-environmental-justice/environment-preview/)：不用自行匯入 CSV，可切換村里所得中位數、環保管理配對紀錄數、土壤／地下水配對紀錄數，並開關土壤場址點位。
- [原首頁：自行匯入資料的原型](https://agp1p7.github.io/taiwan-environmental-justice/)：保留 CSV、GeoJSON 匯入及圖層操作；新增前往資料預覽的連結，不自動跳轉、不替換原功能。

預覽使用2024所得與已保存的環境資料快照。環境紀錄包含歷史及有解除公告資訊的紀錄；未見解除資訊不等於現行列管。紀錄數不是不重複事業家數，零筆配對不代表沒有污染源。

## 驗收狀態

公開預覽網址已通過桌面與手機共12項自動操作檢查，包括載入、設色切換、場址開關、縮放、彈窗與版面。此結果針對預覽頁，不代表新首頁導覽已完成另外的瀏覽器驗收。

- [公開網址驗收報告](reports/deployment/public-browser-acceptance.json)
- [成功部署紀錄](reports/deployment/environment-preview.json)
- [預覽整合品質報告](environment-preview/quality.json)
- [預覽所得品質報告](environment-preview/income-quality.json)

瀏覽器操作通過不代表資料結論已核實。底圖圖磚服務未納入該次驗收，桌面與手機截圖仍須人工審閱；Actions產物設定保留7天。

## 仍未完成

- 現行列管與解除狀態的逐項核對。
- 零座標、未配對紀錄與無效邊界的後續處理；修復候選不會自動套用。
- 村里邊界年代、全國有效性與快照一致性的驗證。
- 行政區搜尋、地址定位與完整場址介紹介面。
- 完整儲存庫歷史、Actions日誌與產物的機密稽核；先前只有局部唯讀檢查，不能視為安全放行。

村里計數只納入可定位且唯一落入有效有名村里的紀錄，不把邊界或重疊點位強制指派。所得單位為千元；不是完整可支配所得或貧窮率。設施分布不等於曝險，空間關聯不等於因果。

## 原首頁的匯入格式

- EMS_S_01 CSV：WGS84Lon/WGS84Lat、EmsNo、FacilityName、IsAir/IsWater/IsWaste；也接受對應小寫欄位。
- EMS_S_07 CSV：WGS84_LNG/WGS84_LAT、SITE_NAME；場址編號的欄位異名仍需依實際檔案核對。
- CSV支援UTF-8或Big5。
- 邊界：經緯度GeoJSON FeatureCollection，保留VILLCODE/COUNTYNAME/TOWNNAME/VILLNAME。
- 所得：villcode,income_median,year；中位數千元、單年度、每村里一筆。

原首頁的匯入資料留在瀏覽器，不上傳；程式庫與底圖需要網路。大量資料效能仍需依實際裝置測試。

## 資料來源與授權

- 預覽頁列出財政部所得統計、環境部EMS_S_01與EMS_S_07來源連結。
- 幾何來源為kiang/salary固定版本，圖資年代仍待核對。
- [預覽所附上游授權](environment-preview/UPSTREAM-LICENSE.txt)。

公開儲存庫中的報告不因未加入網站發布清單而成為私人內容；座標候選詳細報告與其他歷史內容的公開範圍仍須審閱。
