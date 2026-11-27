package model

import "time"

type Job struct {
	ID string `json:"id" bson:"id"`
	JobID string `json:"job_id" bson:"job_id"`
	Company string `json:"company" bson:"company"`
	Title string `json:"title" bson:"title"`
	Location string `json:"location" bson:"location"`
	Description string `json:"description" bson:"description"`
	EmploymentType string `json:"employment_type" bson:"employment_type"`
	Experience string `json:"experience" bson:"experience"`
	Skills []string `json:"skills" bson:"skills"`
	ApplyURL string `json:"apply_url" bson:"apply_url"`
	URL string `json:"url" bson:"url"`
	Source string `json:"source" bson:"source"`
	PostedDate string `json:"posted_date" bson:"posted_date"`
	ValidThrough string `json:"valid_through" bson:"valid_through"`
	CrawledAt time.Time `json:"crawled_at" bson:"crawled_at"`
}
