package main

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"net/http"
	"os"
	"time"
)

const (
	lastCheckFile = "last_check.txt"
	dataURL       = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-diff/main/userInformations.json"
)

type Announcement struct {
	Title      string `json:"title"`
	StartAt    int64  `json:"startAt"`
	BrowseType string `json:"browseType"`
	Path       string `json:"path"`
}

func getLastCheckTime() int64 {
	if _, err := os.Stat(lastCheckFile); err == nil {
		data, err := ioutil.ReadFile(lastCheckFile)
		if err == nil {
			var t int64
			fmt.Sscanf(string(data), "%d", &t)
			return t
		}
	}

	now := time.Now().Unix()
	saveLastCheckTime(now)
	return now
}

func saveLastCheckTime(t int64) {
	ioutil.WriteFile(lastCheckFile, []byte(fmt.Sprintf("%d", t)), 0644)
}

func fetchAnnouncements(w http.ResponseWriter, r *http.Request) {
	lastCheck := getLastCheckTime()
	currentTime := time.Now().Unix()

	resp, err := http.Get(dataURL)
	if err != nil {
		http.Error(w, fmt.Sprintf("エラー: %v", err), http.StatusInternalServerError)
		return
	}
	defer resp.Body.Close()

	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		http.Error(w, fmt.Sprintf("エラー: %v", err), http.StatusInternalServerError)
		return
	}

	var announcements []Announcement
	if err := json.Unmarshal(body, &announcements); err != nil {
		http.Error(w, fmt.Sprintf("エラー: %v", err), http.StatusInternalServerError)
		return
	}

	var newAnnouncements []string

	for _, item := range announcements {
		startAtSeconds := item.StartAt / 1000

		if startAtSeconds >= lastCheck && startAtSeconds <= currentTime {
			if item.BrowseType == "internal" {
				newAnnouncements = append(newAnnouncements, item.Title)
			} else if item.BrowseType == "external" {
				newAnnouncements = append(newAnnouncements, fmt.Sprintf("[%s](%s)", item.Title, item.Path))
			}
		}
	}

	if len(newAnnouncements) > 0 {
		saveLastCheckTime(currentTime)
		for _, a := range newAnnouncements {
			fmt.Fprintln(w, a)
		}
		return
	}

	fmt.Fprintln(w, "新しいお知らせはありません。")
}

func main() {
	http.HandleFunc("/announcements", fetchAnnouncements)
	log.Fatal(http.ListenAndServe(":5000", nil))
}