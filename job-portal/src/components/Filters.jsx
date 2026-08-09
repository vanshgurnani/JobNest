const JOB_TYPES = ['', 'Full-time', 'Part-time', 'Contract', 'Internship', 'Temporary'];
const EXPERIENCE = ['', 'Intern', 'Entry', 'Mid-Senior level', 'Senior', 'Lead', 'Director'];

export default function Filters({ filters, onChange }) {
  function handleChange(key, value) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <aside className="space-y-6">
      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
          Employment Type
        </h3>
        <div className="space-y-1">
          {JOB_TYPES.map((type) => (
            <label
              key={type || 'any'}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors hover:bg-surface-tertiary"
            >
              <input
                type="radio"
                name="employment-type"
                checked={filters.employmentType === type}
                onChange={() => handleChange('employmentType', type)}
                className="h-4 w-4 accent-accent-600"
              />
              <span className="text-ink-secondary">{type || 'Any'}</span>
            </label>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-muted">
          Experience
        </h3>
        <div className="space-y-1">
          {EXPERIENCE.map((level) => (
            <label
              key={level || 'any'}
              className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition-colors hover:bg-surface-tertiary"
            >
              <input
                type="radio"
                name="experience"
                checked={filters.experience === level}
                onChange={() => handleChange('experience', level)}
                className="h-4 w-4 accent-accent-600"
              />
              <span className="text-ink-secondary">{level || 'Any'}</span>
            </label>
          ))}
        </div>
      </div>

      <button
        onClick={() => onChange({ employmentType: '', experience: '' })}
        className="text-sm font-medium text-accent-600 hover:text-accent-700"
      >
        Clear filters
      </button>
    </aside>
  );
}