package storage

import (
	"context"
	"time"

	"github.com/vanshgurnani/jobnest/crawler-go/internal/model"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

type Store struct { client *mongo.Client; jobs *mongo.Collection }

func New(ctx context.Context, uri, database string) (*Store,error) {
	if uri=="" || database=="" { return nil, nilConfigError{} }
	client,err:=mongo.Connect(ctx,options.Client().ApplyURI(uri)); if err!=nil{return nil,err}
	if err=client.Ping(ctx,nil); err!=nil { _=client.Disconnect(ctx); return nil,err }
	collection:=client.Database(database).Collection("jobs")
	_,err=collection.Indexes().CreateMany(ctx,[]mongo.IndexModel{
		{Keys:bson.D{{Key:"id",Value:1}},Options:options.Index().SetUnique(true)},
		{Keys:bson.D{{Key:"company",Value:1},{Key:"crawled_at",Value:-1}}},
	})
	if err!=nil { _=client.Disconnect(ctx); return nil,err }
	return &Store{client:client,jobs:collection},nil
}
type nilConfigError struct{}
func (nilConfigError) Error() string { return "MONGO_URI and MONGO_DB_NAME are required" }
func (s *Store) Close(ctx context.Context) error { if s==nil||s.client==nil{return nil}; return s.client.Disconnect(ctx) }
func (s *Store) Upsert(ctx context.Context, jobs []model.Job) error {
	if s==nil || s.jobs==nil { return nil }
	now:=time.Now().UTC()
	models:=make([]mongo.WriteModel,0,len(jobs))
	for _,j:=range jobs {
		j.CrawledAt=now
		models=append(models,mongo.NewUpdateOneModel().SetFilter(bson.M{"id":j.ID}).SetUpdate(bson.M{"$set":j,"$setOnInsert":bson.M{"first_seen_at":now}}).SetUpsert(true))
	}
	if len(models)==0{return nil}
	_,err:=s.jobs.BulkWrite(ctx,models,options.BulkWrite().SetOrdered(false)); return err
}
