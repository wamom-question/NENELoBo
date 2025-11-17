package main

import (
    "io"
    "net/http"
    "os"
    "time"
)

func main() {
    urls := []string{
        "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/musics.json",
        "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/refs/heads/main/musicDifficulties.json",
    }

	// ディレクトリの作成
	dir := "/app/data/downloads"
	os.MkdirAll(dir, os.ModePerm)

	for _, url := range urls {
		filename := dir + "/" + getFileName(url) // フルパスを指定
		downloadJSON(url, filename)
	}

}

func getFileName(url string) string {
    // URLからファイル名を取得
    parts := strings.Split(url, "/")
    return parts[len(parts)-1]
}

func downloadJSON(url string, filepath string) {
    response, err := http.Get(url)
    if err != nil {
        panic(err)
    }
    defer response.Body.Close()

    file, err := os.Create(filepath)
    if err != nil {
        panic(err)
    }
    defer file.Close()

    io.Copy(file, response.Body)
}
