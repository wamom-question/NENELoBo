package main

import (
    "log"
    "fmt"
    "io"
    "net/http"
    "os"
    "strings"
    "time"
)

func main() {
    urls := []string{
        "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/musics.json",
        "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/musicDifficulties.json",
    }

    // ディレクトリの作成
    dir := "/app/assets"
    if err := os.MkdirAll(dir, os.ModePerm); err != nil {
        log.Fatalf("ディレクトリの作成に失敗しました: %v", err)
    }

    for {
        now := time.Now().In(time.FixedZone("Asia/Tokyo", 9*60*60)) // 日本時間に変換
        if now.Minute() == 0 { // 分が0のとき
            for _, url := range urls {
                filename := dir + "/" + getFileName(url) // フルパスを指定
                if err := downloadJSON(url, filename); err != nil {
                    log.Printf("ダウンロード失敗: %v", err)
                }
            }
            // 1時間待機
            time.Sleep(time.Hour)
        } else {
            // 1分待機
            time.Sleep(time.Minute)
        }
    }
}

func getFileName(url string) string {
    // URLからファイル名を取得
    parts := strings.Split(url, "/")
    return parts[len(parts)-1]
}

func downloadJSON(url string, filepath string) error {
    response, err := http.Get(url)
    if err != nil {
        return err
    }
    defer response.Body.Close()

    // ステータスコードのチェック
    if response.StatusCode != http.StatusOK {
        return fmt.Errorf("ダウンロード失敗: ステータスコード %d", response.StatusCode)
    }

    file, err := os.Create(filepath)
    if err != nil {
        return err
    }
    defer file.Close()

    if _, err := io.Copy(file, response.Body); err != nil {
        return err
    }

    return nil
}
