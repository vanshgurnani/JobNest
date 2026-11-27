package crawler

import (
	"strings"
	"testing"
)

func TestDetectATS(t *testing.T) {
	cases:=[]struct{body,want string}{
		{"https://boards.greenhouse.io/acme","greenhouse"},
		{"https://jobs.lever.co/acme","lever"},
		{"https://jobs.ashbyhq.com/acme","ashby"},
		{"https://careers.example.com","generic"},
	}
	for _,tc:=range cases { if got:=detectATS(tc.body,nil);got!=tc.want {t.Errorf("detectATS(%q)=%q, want %q",tc.body,got,tc.want)} }
}

func TestParseJSONLDJobPosting(t *testing.T) {
	html:=`<html><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Backend Engineer","description":"<p>Build APIs</p>","url":"https://example.com/jobs/1","hiringOrganization":{"@type":"Organization","name":"Example"},"datePosted":"2026-11-01"}</script></html>`
	jobs:=parseHTML([]byte(html),"https://example.com/careers","")
	if len(jobs)!=1 {t.Fatalf("got %d jobs, want 1",len(jobs))}
	if jobs[0].Title!="Backend Engineer" || jobs[0].Company!="Example" || jobs[0].ApplyURL!="https://example.com/jobs/1" {t.Fatalf("unexpected parsed job: %#v",jobs[0])}
	if !strings.Contains(jobs[0].Description,"Build APIs") {t.Fatalf("description not extracted: %q",jobs[0].Description)}
}

func TestStableIDDeterministic(t *testing.T) {
	a:=stableID("https://example.com/job/1","Example","Engineer")
	b:=stableID("https://example.com/job/1","Example","Engineer")
	if a!=b || a=="" {t.Fatalf("stable ID should be deterministic: %q != %q",a,b)}
}
