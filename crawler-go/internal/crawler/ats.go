package crawler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"strings"

	"github.com/vanshgurnani/jobnest/crawler-go/internal/model"
)

func slug(raw string)string { u,e:=url.Parse(raw);if e!=nil{return ""};p:=strings.Split(strings.Trim(u.Path,"/"),"/");if len(p)>0{return p[0]};return "" }
func parseGreenhouse(ctx context.Context,e *Engine,page,company string)([]model.Job,error) {
	board:=slug(page); if board==""{return nil,fmt.Errorf("could not identify Greenhouse board token")}
	return e.apiJobs(ctx,"https://boards-api.greenhouse.io/v1/boards/"+board+"/jobs?content=true","greenhouse",company)
}
func parseLever(ctx context.Context,e *Engine,page,company string)([]model.Job,error) {
	u,_:=url.Parse(page);parts:=strings.Split(strings.Trim(u.Path,"/"),"/");if len(parts)==0{return nil,fmt.Errorf("could not identify Lever site")}
	return e.apiJobs(ctx,"https://api.lever.co/v0/postings/"+parts[0]+"?mode=json","lever",company)
}
func parseAshby(ctx context.Context,e *Engine,page,company string)([]model.Job,error) {
	u,_:=url.Parse(page);parts:=strings.Split(strings.Trim(u.Path,"/"),"/");if len(parts)==0{return nil,fmt.Errorf("could not identify Ashby board")}
	return e.apiJobs(ctx,"https://api.ashbyhq.com/posting-api/job-board/"+parts[0],"ashby",company)
}
func (e *Engine) apiJobs(ctx context.Context,endpoint,source,company string)([]model.Job,error) {
	b,_,err:=e.fetch(ctx,endpoint);if err!=nil{return nil,err}
	var raw any;if err=json.Unmarshal(b,&raw);err!=nil{return nil,err}
	items:=[]any{}
	switch x:=raw.(type){case []any:items=x;case map[string]any:if a,ok:=x["jobs"].([]any);ok{items=a}else if a,ok:=x["data"].([]any);ok{items=a}}
	out:=[]model.Job{}
	for _,item:=range items {
		m,ok:=item.(map[string]any);if !ok{continue}
		get:=func(keys ...string)string{for _,k:=range keys{if v:=m[k];v!=nil&&fmt.Sprint(v)!=""{return fmt.Sprint(v)}};return ""}
		title:=get("title","text","name");link:=get("absolute_url","hostedUrl","url","jobUrl")
		if link==""{link=get("applyUrl")}
		desc:=get("content","description")
		co:=company;if co==""{co=get("company","companyName")}
		loc:=get("location")
		if lm,ok:=m["categories"].(map[string]any);ok&&loc==""{loc=fmt.Sprint(lm["location"])}
		id:=get("id")
		if id==""{id=stableID(link,co,title)}
		out=append(out,model.Job{ID:id,JobID:id,Company:co,Title:title,Location:loc,Description:stripHTML(desc),ApplyURL:link,URL:link,Source:source,PostedDate:get("createdAt","updatedAt","publishedAt")})
	}
	return dedupe(out),nil
}
