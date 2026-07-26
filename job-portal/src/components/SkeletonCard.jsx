export default function SkeletonCard() {
  return (
    <div className="card p-5">
      <div className="flex items-start gap-4">
        <div className="skeleton h-10 w-10 rounded-lg" />
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex justify-between">
            <div className="skeleton h-4 w-3/5 rounded" />
            <div className="skeleton h-3 w-12 rounded" />
          </div>
          <div className="skeleton h-3.5 w-1/3 rounded" />
          <div className="skeleton h-3 w-2/5 rounded" />
          <div className="flex gap-2">
            <div className="skeleton h-6 w-16 rounded-full" />
            <div className="skeleton h-6 w-20 rounded-full" />
            <div className="skeleton h-6 w-14 rounded-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
