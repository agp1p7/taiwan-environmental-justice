# 真實所得圖資驗證
固定第三方來源kiang/salary提交14d01550e2f9cdedb30ee59420b45cd14a1eb518，使用2024所得CSV及來源TopoJSON，轉換後以完整地名配對，不使用舊代碼表。
腳本或workflow提交時自動執行，也可在Actions手動執行Validate real income geometry。成功後下載real-income-validation-site產物（保留7天），解壓後執行python -m http.server 8000，瀏覽localhost:8000。
不部署、不改動原網站、不提交產生資料、不使用API Key；私人儲存庫Actions可能使用額度。
本機轉換與配對邏輯已用人造資料測試，尚未在Actions執行完整來源。圖資年代、全國涵蓋、跨村里拓撲與原始授權未核實，不代表官方快照。幾何只檢查arc連接、封閉與經緯度範圍，不檢查自交。未配對為null，不當成0；沒有環境圖層。來源README與LICENSE隨結果保留。
