FROM postgres:15
WORKDIR /work
COPY feature-builder/build_features.sql /work/build_features.sql
CMD ["bash", "-lc", "psql \"$DATABASE_URL\" -f /work/build_features.sql"]