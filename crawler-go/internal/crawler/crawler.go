package crawler

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/PuerkitoBio/goquery"
	"github.com/vanshgurnani/jobnest/crawler-go/internal/model"
)

type Saver interface { Upsert(context.Context, []model.Job) error }
type Config struct { Workers int; Timeout time.Duration; MaxBody int64; UserAgent string }
func ConfigFromEnv() Config { return Config{Workers:8,Timeout:20*time.Second,MaxBody:5<<20,UserAgent:"JobNestBot/1.0 (+job discovery; respect robots.txt and site terms)"} }
type Engine struct { store Saver; cfg Config; client *http.Client }
func New(s Saver,c Config)*Engine { if c.Workers<1{c.Workers=8}; if c.Timeout==0{c.Timeout=20*time.Second}; if c.MaxBody==0{c.MaxBody=5<<20}; return &Engine{store:s,cfg:c,client:&http.Client{Timeout:c.Timeout,CheckRedirect:func(req *http.Request,via []*http.Request)error{if len(via)>=5{return fmt.Errorf("redirect limit")};return validateTarget(req.URL)}}} }
type Request struct { URL string `json:"url"`; Company string `json:"company,omitempty"`; MaxPages int `json:"max_pages,omitempty"`; Save bool `json:"save,omitempty"` }
type Result struct { Target string `json:"target"`; ATS string `json:"ats"`; Jobs []model.Job `json:"jobs"`; Count int `json:"count"`; Saved bool `json:"saved"` }

func validateTarget(u *url.URL) error {
	if u==nil || (u.Scheme!="http" && u.Scheme!="https") || u.Hostname()=="" { return fmt.Errorf("only http/https URLs are accepted") }
	host:=strings.ToLower(u.Hostname())
	if host=="localhost" || strings.HasSuffix(host,".localhost") || strings.HasSuffix(host,".local") { return fmt.Errorf("local addresses are not crawlable") }
	ips,err:=net.LookupIP(host); if err!=nil{return fmt.Errorf("resolve host: %w",err)}
	for _,ip:=range ips { if ip.IsLoopback()||ip.IsPrivate()||ip.IsLinkLocalUnicast()||ip.IsUnspecified() { return fmt.Errorf("private or local network targets are blocked") } }
	return nil
}
func (e *Engine) Crawl(ctx context.Context, in Request)(Result,error) {
	u,err:=url.Parse(strings.TrimSpace(in.URL)); if err!=nil{return Result{},err}; if err=validateTarget(u);err!=nil{return Result{},err}
	if in.MaxPages<1 { in.MaxPages=5 }; if in.MaxPages>25 { in.MaxPages=25 }
	body,finalURL,err:=e.fetch(ctx,u.String()); if err!=nil{return Result{},err}
	ats:=detectATS(finalURL,body)
	jobs:=[]model.Job{}
	switch ats {
	case "greenhouse": jobs,err=parseGreenhouse(ctx,e,finalURL,in.Company)
	case "lever": jobs,err=parseLever(ctx,e,finalURL,in.Company)
	case "ashby": jobs,err=parseAshby(ctx,e,finalURL,in.Company)
	default: jobs,err=e.parseGenericCrawl(ctx,body,finalURL,in.Company,in.MaxPages)
	}
	if err!=nil { return Result{},err }
	if len(jobs)==0 { jobs=parseHTML(body,finalURL,in.Company) }
	if in.Save && e.store!=nil && len(jobs)>0 { if err=e.store.Upsert(ctx,jobs);err!=nil{return Result{},err} }
	return Result{Target:in.URL,ATS:ats,Jobs:jobs,Count:len(jobs),Saved:in.Save&&len(jobs)>0},nil
}

func (e *Engine) parseGenericCrawl(ctx context.Context, body []byte, pageURL, company string, maxPages int) ([]model.Job,error) {
	jobs:=parseHTML(body,pageURL,company)
	doc,err:=goquery.NewDocumentFromReader(strings.NewReader(string(body))); if err!=nil{return jobs,nil}
	base,_:=url.Parse(pageURL)
	seen:=map[string]bool{pageURL:true}
	candidates:=[]string{}
	doc.Find("a[href]").Each(func(_ int,a *goquery.Selection){
		href,ok:=a.Attr("href"); if !ok{return}
		title:=strings.TrimSpace(a.Text()); if !jobish(title+" "+href){return}
		ref,e:=url.Parse(href); if e!=nil{return}; target:=base.ResolveReference(ref)
		if target.Host!=base.Host || (target.Scheme!="http"&&target.Scheme!="https"){return}
		if !seen[target.String()] {seen[target.String()]=true;candidates=append(candidates,target.String())}
	})
	if maxPages<1 {maxPages=1}; if maxPages>25 {maxPages=25}
	if len(candidates)>maxPages {candidates=candidates[:maxPages]}
	// Fetch candidate job detail pages concurrently, but keep concurrency bounded.
	type result struct { jobs []model.Job }
	sem:=make(chan struct{},e.cfg.Workers); if cap(sem)<1 {sem=make(chan struct{},4)}
	results:=make(chan result,len(candidates))
	var wg sync.WaitGroup
	for _,target:=range candidates {
		wg.Add(1); go func(target string) {
			defer wg.Done()
			select {case sem<-struct{}{}: case <-ctx.Done(): return}
			defer func(){<-sem}()
			page,final,fetchErr:=e.fetch(ctx,target); if fetchErr!=nil{return}
			results<-result{jobs:parseHTML(page,final,company)}
		}(target)
	}
	wg.Wait(); close(results)
	for item:=range results {jobs=append(jobs,item.jobs...)}
	return dedupe(jobs),nil
}

func (e *Engine) fetch(ctx context.Context, raw string)([]byte,string,error) {
	req,err:=http.NewRequestWithContext(ctx,http.MethodGet,raw,nil);if err!=nil{return nil,"",err}
	req.Header.Set("User-Agent",e.cfg.UserAgent);req.Header.Set("Accept","text/html,application/json,application/ld+json,*/*;q=0.8")
	res,err:=e.client.Do(req);if err!=nil{return nil,"",err};defer res.Body.Close()
	if res.StatusCode<200||res.StatusCode>=300{return nil,"",fmt.Errorf("upstream returned HTTP %d",res.StatusCode)}
	b,err:=io.ReadAll(io.LimitReader(res.Body,e.cfg.MaxBody+1));if err!=nil{return nil,"",err};if int64(len(b))>e.cfg.MaxBody{return nil,"",fmt.Errorf("response exceeds size limit")}
	return b,res.Request.URL.String(),nil
}
func detectATS(raw string,b []byte)string {
	s:=strings.ToLower(raw+" "+string(b[:min(len(b),200000)]))
	switch {case strings.Contains(s,"boards.greenhouse.io")||strings.Contains(s,"greenhouse.io/embed/job_board"):return "greenhouse";case strings.Contains(s,"jobs.lever.co")||strings.Contains(s,"api.lever.co/v0/postings"):return "lever";case strings.Contains(s,"jobs.ashbyhq.com")||strings.Contains(s,"ashbyhq.com"):return "ashby";case strings.Contains(s,"smartrecruiters.com"):return "smartrecruiters";case strings.Contains(s,"myworkdayjobs.com"):return "workday";default:return "generic"}
}
func parseHTML(body []byte, pageURL, company string)[]model.Job {
	doc,err:=goquery.NewDocumentFromReader(strings.NewReader(string(body)));if err!=nil{return nil}
	out:=[]model.Job{}
	doc.Find("script[type='application/ld+json']").Each(func(_ int,s *goquery.Selection){
		var v any;if json.Unmarshal([]byte(s.Text()),&v)!=nil{return}
		collectJSONLD(v,&out,pageURL,company)
	})
	if len(out)>0{return dedupe(out)}
	doc.Find("a[href]").Each(func(_ int,a *goquery.Selection){
		href,ok:=a.Attr("href");if !ok{return}; title:=strings.TrimSpace(a.Text())
		if len(title)<4 || !jobish(title+" "+href){return}
		abs,err:=url.Parse(pageURL);if err!=nil{return};ref,err:=url.Parse(href);if err!=nil{return}
		link:=abs.ResolveReference(ref);if link.Host!=abs.Host{return}
		out=append(out,model.Job{Company:company,Title:title,ApplyURL:link.String(),URL:link.String(),Source:"generic"})
	})
	return dedupe(out)
}
func collectJSONLD(v any,out *[]model.Job,pageURL,company string) {
	switch x:=v.(type) {
	case []any: for _,item:=range x{collectJSONLD(item,out,pageURL,company)}
	case map[string]any:
		if graph,ok:=x["@graph"];ok{collectJSONLD(graph,out,pageURL,company)}
		typ:=fmt.Sprint(x["@type"]);if strings.Contains(strings.ToLower(typ),"jobposting") {
			title:=fmt.Sprint(x["title"]);desc:=fmt.Sprint(x["description"]);link:=pageURL
			if u,ok:=x["url"].(string);ok&&u!=""{link=u}
			loc:="";if j,ok:=x["jobLocation"].(map[string]any);ok{if a,ok:=j["address"].(map[string]any);ok{loc=fmt.Sprint(a["addressLocality"]);if c:=fmt.Sprint(a["addressCountry"]);c!="<nil>"{loc+=", "+c}}}
			co:=company;if h,ok:=x["hiringOrganization"].(map[string]any);ok&&fmt.Sprint(h["name"])!="<nil>"{co=fmt.Sprint(h["name"])}
			*out=append(*out,model.Job{ID:stableID(link,co,title),JobID:stableID(link,co,title),Company:co,Title:title,Location:loc,Description:stripHTML(desc),ApplyURL:link,URL:link,Source:"jsonld",PostedDate:fmt.Sprint(x["datePosted"]),ValidThrough:fmt.Sprint(x["validThrough"])})
		}
		for _,value:=range x{if _,ok:=value.(map[string]any);ok{collectJSONLD(value,out,pageURL,company)}}
	}
}
func jobish(s string)bool { s=strings.ToLower(s);for _,k:=range []string{"job","career","opening","position","engineer","developer","analyst","manager","intern"}{if strings.Contains(s,k){return true}};return false }
func stableID(parts ...string)string { sum:=sha256.Sum256([]byte(strings.Join(parts,"|")));return hex.EncodeToString(sum[:])[:24] }
var tags=regexp.MustCompile("<[^>]*>")
var spaces=regexp.MustCompile("\\s+")
func stripHTML(s string)string{return strings.TrimSpace(spaces.ReplaceAllString(tags.ReplaceAllString(s," ")," "))}
func dedupe(in []model.Job)[]model.Job { seen:=map[string]bool{};out:=[]model.Job{};for _,j:=range in{if j.Title==""||j.Title=="<nil>"{continue};if j.ID==""{j.ID=stableID(j.ApplyURL,j.Company,j.Title);j.JobID=j.ID};if seen[j.ID]{continue};seen[j.ID]=true;out=append(out,j)};return out }
