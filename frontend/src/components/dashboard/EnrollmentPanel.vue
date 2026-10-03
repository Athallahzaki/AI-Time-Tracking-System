<script setup>
import EnrollmentForm from './EnrollmentForm.vue';
import EnrolledPersonsList from './EnrolledPersonsList.vue';
</script>

<template>
  <div class="grid gap-5 lg:grid-cols-12">
    <div class="lg:col-span-5">
      <EnrollmentForm />
    </div>
    <div class="lg:col-span-7">
      <EnrolledPersonsList />
    </div>
  </div>
</template>
