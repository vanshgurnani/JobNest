import React from 'react';

export default function SearchBar({ filters, setFilters, onSearch }) {
  function onChange(key) {
    return (e) => {
      setFilters((prev) => ({
        ...prev,
        [key]: e.target.value,
      }));
    };
  }

  function onSubmit(e) {
    e.preventDefault();
    onSearch();
  }

  return (
    <form className="searchbar" onSubmit={onSubmit}>
      <div className="searchbar__grid">
        <label className="field">
          <span className="field__label">Company</span>
          <input
            className="field__input"
            type="text"
            value={filters.company}
            onChange={onChange('company')}
            placeholder="e.g., google"
            autoComplete="off"
          />
        </label>

        <label className="field">
          <span className="field__label">Keyword</span>
          <input
            className="field__input"
            type="text"
            value={filters.keyword}
            onChange={onChange('keyword')}
            placeholder="e.g., engineer"
            autoComplete="off"
          />
        </label>

        <label className="field">
          <span className="field__label">Location</span>
          <input
            className="field__input"
            type="text"
            value={filters.location}
            onChange={onChange('location')}
            placeholder="e.g., remote / London"
            autoComplete="off"
          />
        </label>

        <div className="field field--button">
          <button className="btn" type="submit">
            Search
          </button>
        </div>
      </div>
    </form>
  );
}

